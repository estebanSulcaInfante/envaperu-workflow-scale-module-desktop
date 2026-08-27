import argparse
import getpass
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

from app.runtime.stop_signal import signal_station_stop
from app.runtime.token_store import StationTokenStore, StationTokenStoreError
from app.services.central_api_client import normalize_central_origin
from app.storage.paths import StationPaths


STATION_NOT_RUNNING_EXIT_CODE = 4
PILOT_CONFIG_INVALID_EXIT_CODE = 6
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


def _read_station_environment(paths, environ=None):
    values = dict(os.environ if environ is None else environ)
    environment_file = paths.config / "station.env"
    if not environment_file.is_file():
        return values, environment_file
    for raw_line in environment_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name and name.replace("_", "a").isalnum() and not name[0].isdigit():
            values[name] = value.strip()
    return values, environment_file


def _pilot_config_report(data_root, environ=None):
    """Valida la configuración que el launcher usará para el piloto SCM."""
    paths = _paths(data_root)
    values, environment_file = _read_station_environment(paths, environ)
    issues = []

    raw_operator = str(values.get("SCM_OPERATOR_ID") or "").strip()
    try:
        operator_id = int(raw_operator)
    except (TypeError, ValueError):
        operator_id = None
    if operator_id is None or operator_id <= 0:
        issues.append({
            "code": "SCM_OPERATOR_ID_INVALID",
            "detail": "SCM_OPERATOR_ID debe ser un ID numérico positivo",
        })

    raw_origin = str(values.get("CENTRAL_ORIGIN") or "").strip()
    normalized_origin = None
    if not raw_origin:
        issues.append({
            "code": "CENTRAL_ORIGIN_REQUIRED",
            "detail": "CENTRAL_ORIGIN debe declararse para el piloto SCM",
        })
    else:
        allow_insecure = str(
            values.get("ALLOW_INSECURE_CENTRAL") or "false"
        ).strip().lower() == "true"
        try:
            normalized_origin = normalize_central_origin(
                raw_origin,
                allow_insecure=allow_insecure,
            )
        except ValueError as exc:
            issues.append({
                "code": "CENTRAL_ORIGIN_INVALID",
                "detail": str(exc),
            })

    station_id = None
    if not paths.database.is_file():
        issues.append({
            "code": "STATION_IDENTITY_NOT_INITIALIZED",
            "detail": "La base local no contiene una identidad de estación",
        })
    else:
        try:
            with sqlite3.connect(paths.database) as connection:
                row = connection.execute(
                    "SELECT station_id FROM station_identity LIMIT 1"
                ).fetchone()
            if row is not None:
                station_id = str(uuid.UUID(str(row[0])))
            else:
                raise ValueError("sin fila station_identity")
        except (sqlite3.DatabaseError, ValueError) as exc:
            issues.append({
                "code": "STATION_IDENTITY_INVALID",
                "detail": str(exc),
            })

    token_path = paths.secrets / "station-token.dpapi"
    token_ready = False
    if not token_path.is_file() or token_path.stat().st_size <= 0:
        issues.append({
            "code": "STATION_TOKEN_REQUIRED",
            "detail": "Falta el token central protegido con DPAPI",
        })
    elif os.name == "nt":
        try:
            token_ready = bool(StationTokenStore(token_path).read())
            if not token_ready:
                raise StationTokenStoreError("token vacío")
        except (StationTokenStoreError, UnicodeError) as exc:
            issues.append({
                "code": "STATION_TOKEN_INVALID",
                "detail": str(exc),
            })
    else:
        # CI no posee DPAPI; valida presencia. En Windows se descifra arriba.
        token_ready = True

    return {
        "status": (
            "PILOT_CONFIG_READY" if not issues else "PILOT_CONFIG_INVALID"
        ),
        "valid": not issues,
        "issues": issues,
        "environment_file": str(environment_file),
        "scm_operator_id": operator_id if operator_id and operator_id > 0 else None,
        "central_origin": normalized_origin,
        "station_id": station_id,
        "token_storage": "DPAPI" if token_ready else None,
    }


def _validate_pilot_config(data_root):
    report = _pilot_config_report(data_root)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["valid"] else PILOT_CONFIG_INVALID_EXIT_CODE


def main(argv=None):
    parser = argparse.ArgumentParser(description="Control a weighing station runtime")
    parser.add_argument(
        "command",
        choices=["stop", "identity", "provision-token", "validate-pilot-config"],
    )
    parser.add_argument("--station-id", default=DEFAULT_STATION_ID)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--token-stdin", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "identity":
        return _show_identity(args.data_root)
    if args.command == "provision-token":
        return _provision_token(args.data_root, args.token_stdin)
    if args.command == "validate-pilot-config":
        return _validate_pilot_config(args.data_root)
    if signal_station_stop(args.station_id):
        print(f"STOP_SIGNAL_SENT station_id={args.station_id}", flush=True)
        return 0

    print(f"STATION_NOT_RUNNING station_id={args.station_id}", flush=True)
    return STATION_NOT_RUNNING_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
