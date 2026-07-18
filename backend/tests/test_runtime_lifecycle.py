import os
import sys
import threading
import time

import pytest
import serial


os.environ["SYNC_ENABLED"] = "false"

from app import create_app
from app.runtime.lifecycle import RuntimeState, StationLifecycle
from app.services.printer_service import PrinterService
from app.services.scale_service import ScaleService


def test_stopping_runtime_is_not_ready_and_rejects_mutations(tmp_path):
    runtime_state = RuntimeState()
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}",
            "RUNTIME_STATE": runtime_state,
        },
        start_workers=False,
    )
    client = app.test_client()

    runtime_state.mark_ready()
    assert client.get("/api/local/v1/health/ready").status_code == 200

    assert runtime_state.begin_stopping() is True
    ready_response = client.get("/api/local/v1/health/ready")
    mutation_response = client.post("/api/pesajes", json={})

    assert ready_response.status_code == 503
    assert ready_response.get_json()["status"] == "STOPPING"
    assert mutation_response.status_code == 503
    assert mutation_response.get_json()["code"] == "RUNTIME_STOPPING"


def test_scale_shutdown_interrupts_reconnect_wait_and_closes_serial():
    serial_closed = threading.Event()
    reconnect_attempted = threading.Event()

    class FakeSerialConnection:
        is_open = True

        def close(self):
            self.is_open = False
            serial_closed.set()

    service = ScaleService(port="COM-TEST", baud_rate=9600)
    service.serial_connection = FakeSerialConnection()

    def disconnected_read():
        raise serial.SerialException("test disconnect")

    def unexpected_reconnect():
        reconnect_attempted.set()
        return False

    service.read_weight = disconnected_read
    service.connect = unexpected_reconnect
    service.start_listening(lambda weight: None)
    assert serial_closed.wait(timeout=1)

    started_at = time.monotonic()
    stopped = service.shutdown(timeout=1)
    elapsed = time.monotonic() - started_at

    assert stopped is True
    assert elapsed < 0.75
    assert reconnect_attempted.is_set() is False
    assert service.is_listening is False
    assert service._listener_thread is None


def test_printer_shutdown_drains_active_print_before_disconnect(monkeypatch):
    write_started = threading.Event()
    release_write = threading.Event()
    printer_closed = threading.Event()

    class FakeWin32Print:
        def OpenPrinter(self, name):
            return object()

        def StartDocPrinter(self, handle, level, document):
            return 1

        def StartPagePrinter(self, handle):
            return None

        def WritePrinter(self, handle, data):
            write_started.set()
            release_write.wait(timeout=2)

        def EndPagePrinter(self, handle):
            return None

        def EndDocPrinter(self, handle):
            return None

        def ClosePrinter(self, handle):
            printer_closed.set()

    monkeypatch.setitem(sys.modules, "win32print", FakeWin32Print())
    printer = PrinterService(printer_type="TSPL", printer_name="TEST-PRINTER")
    assert printer.connect() is True

    print_thread = threading.Thread(target=printer.print_tspl, args=("SIZE 1,1",))
    print_thread.start()
    assert write_started.wait(timeout=1)

    release_timer = threading.Timer(0.2, release_write.set)
    release_timer.start()
    started_at = time.monotonic()
    try:
        drained = printer.shutdown(timeout=1)
    finally:
        release_write.set()
        release_timer.cancel()
        print_thread.join(timeout=1)

    elapsed = time.monotonic() - started_at
    assert drained is True
    assert elapsed >= 0.15
    assert print_thread.is_alive() is False
    assert printer_closed.is_set() is True
    assert printer._connected is False


def test_lifecycle_continues_after_resource_shutdown_failure(tmp_path):
    events = []

    class FakeDispatcher:
        def shutdown(self, cancel_pending, timeout):
            events.append("dispatcher")

    class FakeServer:
        task_dispatcher = FakeDispatcher()
        _map = {}

        def close(self):
            events.append("server")

    def failing_scale(timeout):
        events.append("scale")
        raise RuntimeError("scale close failed")

    def stop_printer(timeout):
        events.append("printer")
        return True

    def stop_sync(timeout):
        events.append("sync")
        return True

    def stop_socketio(timeout):
        events.append("socketio")
        return True

    emitted = []
    runtime_state = RuntimeState()
    runtime_state.mark_ready()
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'errors.db').as_posix()}",
            "RUNTIME_STATE": runtime_state,
        },
        start_workers=False,
    )
    lifecycle = StationLifecycle(
        app=app,
        server=FakeServer(),
        runtime_state=runtime_state,
        scale_shutdown=failing_scale,
        printer_shutdown=stop_printer,
        sync_shutdown=stop_sync,
        socketio_shutdown=stop_socketio,
        emit=emitted.append,
    )

    assert lifecycle.shutdown() is False
    assert events == [
        "scale",
        "printer",
        "sync",
        "server",
        "socketio",
        "dispatcher",
    ]
    assert runtime_state.status == RuntimeState.STOPPED
    assert any("RUNTIME_SHUTDOWN_ERROR step=scale" in item for item in emitted)
    assert emitted[-1] == "RUNTIME_STOPPED errors=1"
