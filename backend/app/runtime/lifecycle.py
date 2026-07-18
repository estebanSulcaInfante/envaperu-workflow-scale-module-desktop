import threading
import time

from flask import jsonify, request


class RuntimeState:
    STARTING = "STARTING"
    READY = "READY"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"

    def __init__(self):
        self._status = self.STARTING
        self._lock = threading.Lock()

    @property
    def status(self):
        with self._lock:
            return self._status

    def mark_ready(self):
        with self._lock:
            if self._status == self.STARTING:
                self._status = self.READY

    def begin_stopping(self):
        with self._lock:
            if self._status in (self.STOPPING, self.STOPPED):
                return False
            self._status = self.STOPPING
            return True

    def mark_stopped(self):
        with self._lock:
            self._status = self.STOPPED


def install_runtime_guard(app):
    @app.before_request
    def reject_mutations_while_stopping():
        runtime_state = app.config.get("RUNTIME_STATE")
        if runtime_state is None or runtime_state.status != RuntimeState.STOPPING:
            return None
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        return (
            jsonify(
                {
                    "status": "error",
                    "code": "RUNTIME_STOPPING",
                    "message": "La estacion se esta deteniendo; no acepta cambios.",
                }
            ),
            503,
        )


class StationLifecycle:
    def __init__(
        self,
        app,
        server,
        runtime_state,
        timeout=10,
        scale_shutdown=None,
        printer_shutdown=None,
        sync_shutdown=None,
        socketio_shutdown=None,
        emit=print,
    ):
        self.app = app
        self.server = server
        self.runtime_state = runtime_state
        self.timeout = timeout
        self.scale_shutdown = scale_shutdown or self._shutdown_scale
        self.printer_shutdown = printer_shutdown or self._shutdown_printer
        self.sync_shutdown = sync_shutdown or self._shutdown_sync
        self.socketio_shutdown = socketio_shutdown or self._shutdown_socketio
        self.emit = emit
        self.complete = threading.Event()
        self._start_lock = threading.Lock()
        self._started = False
        self.succeeded = None
        self.errors = []

    @staticmethod
    def _shutdown_scale(timeout):
        from app.services.scale_service import shutdown_scale_service

        return shutdown_scale_service(timeout=timeout)

    @staticmethod
    def _shutdown_printer(timeout):
        from app.services.printer_service import shutdown_printer_service

        return shutdown_printer_service(timeout=timeout)

    @staticmethod
    def _shutdown_sync(timeout):
        from app import stop_background_workers

        return stop_background_workers(timeout=timeout)

    @staticmethod
    def _shutdown_socketio(timeout):
        from app import socketio

        if socketio.server is None:
            return True
        engine_server = socketio.server.eio
        for engine_socket in engine_server.sockets.copy().values():
            engine_socket.close(
                wait=False,
                abort=False,
                reason=engine_server.reason.SERVER_DISCONNECT,
            )
        engine_server.sockets = {}
        socketio.server.shutdown()
        return True

    def _remaining(self, deadline):
        return max(0.1, deadline - time.monotonic())

    def _close_server(self, timeout):
        dispatcher = getattr(self.server, "task_dispatcher", None)
        server_map = getattr(self.server, "_map", None)
        trigger = getattr(self.server, "trigger", None)

        if dispatcher is not None and trigger is not None:
            from waitress import wasyncore

            # Stop accepting first, but keep the trigger alive while active
            # polling requests finish and wake their Waitress channels.
            wasyncore.dispatcher.close(self.server)
            self.socketio_shutdown(timeout)
            dispatcher.shutdown(cancel_pending=True, timeout=timeout)
            trigger.close()
            if server_map:
                wasyncore.close_all(server_map)
            return True

        self.server.close()
        self.socketio_shutdown(timeout)
        if dispatcher is not None:
            dispatcher.shutdown(cancel_pending=True, timeout=timeout)
        return True

    def _record_error(self, step, error):
        detail = f"{type(error).__name__}: {error}".replace("\n", " ")
        self.errors.append({"step": step, "detail": detail})
        self.emit(f"RUNTIME_SHUTDOWN_ERROR step={step} error={detail}")

    def _run_step(self, step, callback, deadline):
        try:
            result = callback(self._remaining(deadline))
            if result is False:
                self._record_error(step, RuntimeError("shutdown timeout"))
        except Exception as exc:
            self._record_error(step, exc)

    def _close_database(self, timeout):
        with self.app.app_context():
            from app import db

            db.session.remove()
        return True

    def shutdown(self):
        with self._start_lock:
            if self._started:
                already_started = True
            else:
                self._started = True
                already_started = False

        if already_started:
            self.complete.wait(timeout=self.timeout + 1)
            return self.complete.is_set() and bool(self.succeeded)

        deadline = time.monotonic() + self.timeout
        self.runtime_state.begin_stopping()
        self.emit("RUNTIME_STOPPING")

        try:
            self._run_step("scale", self.scale_shutdown, deadline)
            self._run_step("printer", self.printer_shutdown, deadline)
            self._run_step("sync", self.sync_shutdown, deadline)
            self._run_step("database", self._close_database, deadline)
            self._run_step("server", self._close_server, deadline)
            self.runtime_state.mark_stopped()
            self.succeeded = not self.errors
            if self.errors:
                self.emit(f"RUNTIME_STOPPED errors={len(self.errors)}")
            else:
                self.emit("RUNTIME_STOPPED")
            return self.succeeded
        finally:
            self.complete.set()
