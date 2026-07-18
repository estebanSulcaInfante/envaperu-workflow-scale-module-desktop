import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

from waitress.server import create_server

from app import create_app
from app.runtime.lifecycle import RuntimeState, StationLifecycle
from app.runtime.single_instance import (
    INSTANCE_ALREADY_RUNNING_EXIT_CODE,
    InstanceAlreadyRunning,
    StationMutex,
)
from app.runtime.stop_signal import StationStopSignal
from app.storage.paths import resolve_station_storage


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 5050
DEFAULT_THREADS = 4
DEFAULT_STATION_ID = "PESAJE-PLANTA-01"
SHUTDOWN_INCOMPLETE_EXIT_CODE = 5
MODULE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATIC_DIR = MODULE_DIR / "frontend" / "dist"


def _parser():
    parser = argparse.ArgumentParser(description="EnvaPeru weighing station runtime")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("API_PORT", DEFAULT_PORT)),
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=int(os.getenv("STATION_THREADS", DEFAULT_THREADS)),
    )
    parser.add_argument(
        "--station-id",
        default=os.getenv("STATION_ID", DEFAULT_STATION_ID),
    )
    parser.add_argument(
        "--static-dir",
        type=Path,
        default=Path(os.getenv("STATION_STATIC_DIR", DEFAULT_STATIC_DIR)),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=os.getenv("STATION_DATA_ROOT"),
        help="Persistent station root; defaults to ProgramData on Windows",
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        default=(
            Path(os.environ["STATION_DATABASE_PATH"])
            if os.getenv("STATION_DATABASE_PATH")
            else None
        ),
        help="Compatibility override for a specific SQLite file",
    )
    parser.add_argument("--open-browser", action="store_true")
    return parser


def _database_uri(database_path):
    resolved = database_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{resolved.as_posix()}"


def build_release_app(args, runtime_state=None):
    runtime_state = runtime_state or RuntimeState()
    paths, database_path = resolve_station_storage(
        data_root=args.data_root,
        database_path=args.database_path,
    )
    storage_config = paths.as_config()
    storage_config.update(
        {
            "STATION_DATABASE_PATH": str(database_path),
            "SQLALCHEMY_DATABASE_URI": _database_uri(database_path),
            "STATION_TOKEN_FILE": str(paths.secrets / "station-token.dpapi"),
        }
    )
    return create_app(
        config_overrides={
            "DEBUG": False,
            "USE_RELOADER": False,
            "RUNTIME_PROFILE": "RELEASE",
            "RUNTIME_SERVER": "waitress",
            "SAME_ORIGIN_ONLY": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": True,
            "STATION_ID": args.station_id,
            "STATION_CODE": args.station_id,
            "RUNTIME_STATE": runtime_state,
            **storage_config,
        },
        static_dir=args.static_dir,
        start_workers=True,
    )


def main(argv=None):
    args = _parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    if args.threads < 2:
        raise SystemExit("threads must be at least 2 for Socket.IO polling")

    mutex = StationMutex(args.station_id)
    try:
        mutex.acquire()
    except InstanceAlreadyRunning:
        print(
            f"INSTANCE_ALREADY_RUNNING station_id={args.station_id}",
            file=sys.stderr,
            flush=True,
        )
        return INSTANCE_ALREADY_RUNNING_EXIT_CODE

    stop_signal = None
    watcher_stop = threading.Event()
    watcher_thread = None
    lifecycle = None

    try:
        runtime_state = RuntimeState()
        stop_signal = StationStopSignal(args.station_id)
        app = build_release_app(args, runtime_state=runtime_state)
        server = create_server(
            app,
            host=LOOPBACK_HOST,
            port=args.port,
            threads=args.threads,
        )
        lifecycle = StationLifecycle(
            app=app,
            server=server,
            runtime_state=runtime_state,
            timeout=10,
        )

        def watch_for_stop():
            while not watcher_stop.is_set():
                if stop_signal.wait(timeout=0.25):
                    lifecycle.shutdown()
                    return

        watcher_thread = threading.Thread(
            target=watch_for_stop,
            daemon=True,
            name="StationStopWatcher",
        )
        watcher_thread.start()
        runtime_state.mark_ready()
        print(
            f"RUNTIME_READY origin=http://{LOOPBACK_HOST}:{args.port} "
            f"station_id={args.station_id}",
            flush=True,
        )
        if args.open_browser:
            browser_timer = threading.Timer(
                0.5,
                webbrowser.open,
                args=(f"http://{LOOPBACK_HOST}:{args.port}",),
            )
            browser_timer.daemon = True
            browser_timer.start()
        server.run()
        shutdown_ok = lifecycle.shutdown()
        return 0 if shutdown_ok else SHUTDOWN_INCOMPLETE_EXIT_CODE
    except KeyboardInterrupt:
        if lifecycle is None:
            return 0
        shutdown_ok = lifecycle.shutdown()
        return 0 if shutdown_ok else SHUTDOWN_INCOMPLETE_EXIT_CODE
    finally:
        if lifecycle is not None:
            lifecycle.shutdown()
        watcher_stop.set()
        if watcher_thread is not None and watcher_thread is not threading.current_thread():
            watcher_thread.join(timeout=1)
        if stop_signal is not None:
            stop_signal.close()
        mutex.release()


if __name__ == "__main__":
    raise SystemExit(main())
