import argparse
import os
import sqlite3
import sys
from pathlib import Path

from app.runtime.token_store import StationTokenStore
from app.services.central_api_client import CentralApiClient, CentralApiError
from app.services.legacy_history_export import (
    CONTRACT_VERSION,
    LegacyHistoryExportError,
    build_legacy_history_export,
    export_summary,
    publish_legacy_history,
)
from app.storage.paths import StationPaths


def _parser():
    parser = argparse.ArgumentParser(
        description="Inspect or publish a static legacy weighing SQLite backup"
    )
    parser.add_argument("command", choices=["inspect", "publish"])
    parser.add_argument("source", type=Path, help="Static pesajes.db copy")
    parser.add_argument("--station-id")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--central-origin", default=os.getenv("CENTRAL_ORIGIN"))
    parser.add_argument("--station-version", default="1.1.0-pilot")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument(
        "--confirm-static-backup",
        action="store_true",
        help="Required for publish; confirms source is not the live station DB",
    )
    parser.add_argument("--allow-insecure-central", action="store_true")
    return parser


def _paths(data_root):
    return StationPaths(data_root) if data_root else StationPaths.from_environment()


def _identity(paths):
    if not paths.database.is_file():
        raise LegacyHistoryExportError(
            "no existe la base activa con station_identity; use --station-id"
        )
    try:
        with sqlite3.connect(f"{paths.database.resolve().as_uri()}?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT station_id FROM station_identity LIMIT 1"
            ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise LegacyHistoryExportError(
            "station_identity no pudo leerse; use --station-id"
        ) from exc
    if row is None:
        raise LegacyHistoryExportError("station_identity no existe; use --station-id")
    return row[0]


def main(argv=None):
    args = _parser().parse_args(argv)
    paths = _paths(args.data_root)
    try:
        station_id = args.station_id or _identity(paths)
        export = build_legacy_history_export(
            args.source,
            station_id,
            chunk_size=args.chunk_size,
        )
        print(export_summary(export))
        if args.command == "inspect":
            print("LEGACY_HISTORY_INSPECTED no_data_transmitted=true")
            return 0

        if not args.confirm_static_backup:
            raise LegacyHistoryExportError(
                "publish requiere --confirm-static-backup"
            )
        if args.source.resolve() == paths.database.resolve():
            raise LegacyHistoryExportError(
                "publish no admite la base activa; cree una copia cerrada"
            )
        if not args.central_origin:
            raise LegacyHistoryExportError("--central-origin es requerido")
        token = StationTokenStore(paths.secrets / "station-token.dpapi").read()
        if not token:
            raise LegacyHistoryExportError(
                "token central no provisionado en station-token.dpapi"
            )
        client = CentralApiClient(
            args.central_origin,
            token,
            args.station_version,
            allow_insecure=args.allow_insecure_central,
        )
        capabilities = client.get_capabilities()
        supported = capabilities.get("supported_contracts", {}).get("weight_event", [])
        if CONTRACT_VERSION not in supported:
            raise LegacyHistoryExportError(
                f"API central no anuncia {CONTRACT_VERSION}"
            )
        ack = publish_legacy_history(client, station_id, export)
        print(
            "LEGACY_HISTORY_PUBLISHED "
            f"import_id={export.import_id} status={ack['status']} "
            f"chunks={len(export.chunks)}"
        )
        return 0
    except (LegacyHistoryExportError, CentralApiError, ValueError) as exc:
        print(f"LEGACY_HISTORY_ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
