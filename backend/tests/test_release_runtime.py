import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests
import socketio


pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
STATION_MAIN = BACKEND_DIR / "station_main.py"
STATION_CONTROL = BACKEND_DIR / "station_control.py"
INSTANCE_ALREADY_RUNNING_EXIT_CODE = 73


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _station_command(port, static_dir, database_path, station_id):
    return [
        sys.executable,
        str(STATION_MAIN),
        "--port",
        str(port),
        "--static-dir",
        str(static_dir),
        "--database-path",
        str(database_path),
        "--station-id",
        station_id,
    ]


def _start_station(command):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        command,
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _wait_until_live(process, origin, timeout=15):
    deadline = time.monotonic() + timeout
    last_error = None

    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            pytest.fail(
                f"Station exited before liveness (code={process.returncode}):\n{output}"
            )

        try:
            response = requests.get(
                f"{origin}/api/local/v1/health/live",
                timeout=0.5,
            )
            if response.status_code == 200:
                return response
        except requests.RequestException as exc:
            last_error = exc

        time.sleep(0.1)

    pytest.fail(f"Station did not become live: {last_error}")


def _stop_process(process):
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _signal_station_stop(station_id):
    return subprocess.run(
        [
            sys.executable,
            str(STATION_CONTROL),
            "stop",
            "--station-id",
            station_id,
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        check=False,
    )


def test_release_profile_serves_ui_and_socketio_same_origin(tmp_path):
    static_dir = tmp_path / "dist"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text(
        '<!doctype html><html><body><div id="root">station-ui</div></body></html>',
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text(
        'window.__STATION_ASSET__ = "loaded";',
        encoding="utf-8",
    )

    station_id = f"TEST-{uuid.uuid4().hex}"
    primary_port = _free_port()
    primary_origin = f"http://127.0.0.1:{primary_port}"
    primary = _start_station(
        _station_command(
            primary_port,
            static_dir,
            tmp_path / "station.db",
            station_id,
        )
    )
    sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False)

    try:
        live_response = _wait_until_live(primary, primary_origin)
        live = live_response.json()
        assert live == {
            "debug": False,
            "profile": "RELEASE",
            "reloader": False,
            "server": "waitress",
            "status": "LIVE",
        }

        ready_response = requests.get(
            f"{primary_origin}/api/local/v1/health/ready",
            timeout=2,
        )
        assert ready_response.status_code == 200
        ready = ready_response.json()
        assert ready["issues"] == []
        assert ready["status"] == "READY"
        assert ready["central"]["state"] == "CENTRAL_NOT_PROVISIONED"
        assert ready["central"]["last_central_ack_utc"] is None

        index_response = requests.get(f"{primary_origin}/", timeout=2)
        assert index_response.status_code == 200
        assert "station-ui" in index_response.text
        assert "no-store" in index_response.headers["Cache-Control"]

        asset_response = requests.get(
            f"{primary_origin}/assets/app.js",
            timeout=2,
        )
        assert asset_response.status_code == 200
        assert "__STATION_ASSET__" in asset_response.text
        assert "immutable" in asset_response.headers["Cache-Control"]

        spa_response = requests.get(f"{primary_origin}/pesajes/hoy", timeout=2)
        assert spa_response.status_code == 200
        assert "station-ui" in spa_response.text

        missing_api_response = requests.get(
            f"{primary_origin}/api/route-that-does-not-exist",
            timeout=2,
        )
        assert missing_api_response.status_code == 404
        assert "station-ui" not in missing_api_response.text

        cross_origin_response = requests.get(
            f"{primary_origin}/api/local/v1/health/live",
            headers={"Origin": "http://example.invalid"},
            timeout=2,
        )
        assert "Access-Control-Allow-Origin" not in cross_origin_response.headers

        rejected_socket_response = requests.get(
            f"{primary_origin}/socket.io/?EIO=4&transport=polling",
            headers={"Origin": "http://example.invalid"},
            timeout=2,
        )
        assert rejected_socket_response.status_code == 400
        assert "Not an accepted origin" in rejected_socket_response.text

        sio.connect(primary_origin, transports=["polling"], wait_timeout=5)
        assert sio.connected is True
        assert sio.transport() == "polling"

        second_port = _free_port()
        second = _start_station(
            _station_command(
                second_port,
                static_dir,
                tmp_path / "second.db",
                station_id,
            )
        )
        second_output, _ = second.communicate(timeout=5)
        assert second.returncode == INSTANCE_ALREADY_RUNNING_EXIT_CODE
        assert "INSTANCE_ALREADY_RUNNING" in second_output
    finally:
        if sio.connected:
            sio.disconnect()
        _stop_process(primary)


def test_frontend_clients_use_release_same_origin_contract():
    api_source = (FRONTEND_DIR / "src" / "services" / "api.js").read_text(
        encoding="utf-8"
    )
    socket_source = (
        FRONTEND_DIR / "src" / "services" / "socket.js"
    ).read_text(encoding="utf-8")
    vite_source = (FRONTEND_DIR / "vite.config.js").read_text(encoding="utf-8")

    assert "baseURL: '/api'" in api_source
    assert "http://127.0.0.1" not in api_source

    assert "io({" in socket_source
    assert "transports: ['polling']" in socket_source
    assert "http://127.0.0.1" not in socket_source
    assert "'websocket'" not in socket_source

    assert "base: '/'" in vite_source


def test_windows_launcher_uses_single_release_runtime():
    launcher_source = (BACKEND_DIR.parent / "start-windows.bat").read_text(
        encoding="utf-8"
    )

    assert "station_main.py" in launcher_source
    assert "npm run dev" not in launcher_source
    assert "cmd /k" not in launcher_source

    stop_launcher_source = (BACKEND_DIR.parent / "stop-windows.bat").read_text(
        encoding="utf-8"
    )
    assert "station_control.py stop" in stop_launcher_source
    assert "taskkill" not in stop_launcher_source.lower()

    development_source = (BACKEND_DIR / "run.py").read_text(encoding="utf-8")
    assert "use_reloader=False" in development_source


def test_windows_installer_never_opens_legacy_database():
    installer_source = (BACKEND_DIR.parent / "install-windows.bat").read_text(
        encoding="utf-8"
    )
    importer_source = (
        BACKEND_DIR.parent / "import-legacy-windows.bat"
    ).read_text(encoding="utf-8")

    assert "create_app" not in installer_source
    assert "init_db.py" not in installer_source
    assert "station_storage.py import-legacy" in importer_source
    assert "--replace-existing" in importer_source


def test_release_stop_signal_closes_runtime_and_reuses_port(tmp_path):
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        '<!doctype html><html><body><div id="root">station-ui</div></body></html>',
        encoding="utf-8",
    )

    station_id = f"TEST-STOP-{uuid.uuid4().hex}"
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    primary = _start_station(
        _station_command(port, static_dir, tmp_path / "primary.db", station_id)
    )
    replacement = None
    sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False)

    try:
        _wait_until_live(primary, origin)
        sio.connect(origin, transports=["polling"], wait_timeout=5)

        stop_result = _signal_station_stop(station_id)
        assert stop_result.returncode == 0, stop_result.stderr
        assert "STOP_SIGNAL_SENT" in stop_result.stdout

        primary_output, _ = primary.communicate(timeout=10)
        assert primary.returncode == 0
        assert "RUNTIME_STOPPING" in primary_output
        assert "RUNTIME_STOPPED" in primary_output
        assert "Traceback" not in primary_output
        assert "Exception when servicing" not in primary_output

        replacement = _start_station(
            _station_command(
                port,
                static_dir,
                tmp_path / "replacement.db",
                station_id,
            )
        )
        _wait_until_live(replacement, origin)

        replacement_stop = _signal_station_stop(station_id)
        assert replacement_stop.returncode == 0
        replacement_output, _ = replacement.communicate(timeout=10)
        assert replacement.returncode == 0
        assert "RUNTIME_STOPPED" in replacement_output
        assert "Traceback" not in replacement_output
        assert "Exception when servicing" not in replacement_output
    finally:
        if sio.connected:
            sio.disconnect()
        _stop_process(primary)
        if replacement is not None:
            _stop_process(replacement)
