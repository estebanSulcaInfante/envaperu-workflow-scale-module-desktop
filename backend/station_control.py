import argparse
import getpass
import sqlite3
import sys
from pathlib import Path

from app.runtime.stop_signal import signal_station_stop
from app.runtime.token_store import StationTokenStore
from app.storage.paths import StationPaths


STATION_NOT_RUNNING_EXIT_CODE = 4
DEFAULT_STATION_ID = "PESAJE-PLANTA-01"


def _paths(data_root):
    return StationPaths(Path(data_root)) if data_root else StationPaths.from_environment()


def _show_identity(data_root):
    paths = _paths(data_root)
    if not paths.database.is_file():
        print("STATION_IDENTITY_NOT_INITIALIZED", file=sys.stderr)
        return 2
    try:
        with sqlite3.connect(paths.database) as connection:
            row = connection.execute(
                "SELECT station_id, station_code FROM station_identity LIMIT 1"
            ).fetchone()
    except sqlite3.DatabaseError as exc:
        print(f"STATION_IDENTITY_READ_ERROR error={exc}", file=sys.stderr)
        return 2
    if row is None:
        print("STATION_IDENTITY_NOT_INITIALIZED", file=sys.stderr)
        return 2
    print(f"STATION_IDENTITY station_id={row[0]} code={row[1]}")
    return 0


def _provision_token(data_root, token_stdin):
    paths = _paths(data_root)
    paths.ensure_layout()
    token = (
        sys.stdin.readline().strip()
        if token_stdin
        else getpass.getpass("Token central: ").strip()
    )
    if not token:
        print("STATION_TOKEN_REQUIRED", file=sys.stderr)
        return 2
    StationTokenStore(paths.secrets / "station-token.dpapi").write(token)
    print("STATION_TOKEN_PROVISIONED storage=DPAPI")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Control a weighing station runtime")
    parser.add_argument("command", choices=["stop", "identity", "provision-token"])
    parser.add_argument("--station-id", default=DEFAULT_STATION_ID)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--token-stdin", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "identity":
        return _show_identity(args.data_root)
    if args.command == "provision-token":
        return _provision_token(args.data_root, args.token_stdin)
    if signal_station_stop(args.station_id):
        print(f"STOP_SIGNAL_SENT station_id={args.station_id}", flush=True)
        return 0

    print(f"STATION_NOT_RUNNING station_id={args.station_id}", flush=True)
    return STATION_NOT_RUNNING_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
