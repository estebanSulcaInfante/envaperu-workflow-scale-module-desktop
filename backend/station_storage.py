import argparse
import json
import os
import sys
from pathlib import Path

from app.runtime.single_instance import InstanceAlreadyRunning, StationMutex
from app.storage.backup import BackupError, BackupService, inspect_database
from app.storage.migrations import SchemaMigrationError, migrate_sqlite_database
from app.storage.paths import resolve_station_storage


DEFAULT_STATION_ID = "PESAJE-PLANTA-01"
STATION_ACTIVE_EXIT_CODE = 6
STORAGE_ERROR_EXIT_CODE = 7


def _parser():
    parser = argparse.ArgumentParser(
        description="Maintain EnvaPeru weighing station persistence"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=os.getenv("STATION_DATA_ROOT"),
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        default=(
            Path(os.environ["STATION_DATABASE_PATH"])
            if os.getenv("STATION_DATABASE_PATH")
            else None
        ),
    )
    parser.add_argument(
        "--station-id",
        default=os.getenv("STATION_ID", DEFAULT_STATION_ID),
    )
    parser.add_argument(
        "--retention-count",
        type=int,
        default=int(os.getenv("BACKUP_RETENTION_COUNT", "14")),
    )

    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="Create and verify a SQLite backup")
    backup.add_argument("--reason", default="manual")

    verify = commands.add_parser("verify", help="Verify backup hash and integrity")
    verify.add_argument("backup_path", type=Path)

    commands.add_parser("migrate", help="Apply pending versioned migrations")

    restore = commands.add_parser(
        "restore",
        help="Restore a verified backup while the station is stopped",
    )
    restore.add_argument("backup_path", type=Path)

    import_legacy = commands.add_parser(
        "import-legacy",
        help="Import, migrate, verify and atomically activate a legacy database",
    )
    import_legacy.add_argument("source_database", type=Path)
    import_legacy.add_argument(
        "--replace-existing",
        action="store_true",
        help="Allow replacement when the destination already has business data",
    )
    return parser


def _record_payload(record):
    return {
        "path": str(record.path),
        "manifest_path": str(record.manifest_path),
        "station_id": record.station_id,
        "schema_version": record.schema_version,
        "created_at_utc": record.created_at_utc,
        "reason": record.reason,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "integrity_check": record.integrity_check,
    }


def _inspection_payload(inspection):
    return {
        "path": str(inspection.path),
        "size_bytes": inspection.size_bytes,
        "sha256": inspection.sha256,
        "integrity_check": inspection.integrity_check,
        "schema_version": inspection.schema_version,
        "table_counts": inspection.table_counts,
        "max_ids": inspection.max_ids,
    }


def _print_result(event, **payload):
    print(json.dumps({"event": event, **payload}, sort_keys=True), flush=True)


def main(argv=None):
    args = _parser().parse_args(argv)
    mutex = None
    try:
        paths, database_path = resolve_station_storage(
            data_root=args.data_root,
            database_path=args.database_path,
        )
        service = BackupService(
            database_path=database_path,
            backup_dir=paths.backups,
            station_id=args.station_id,
            retention_count=args.retention_count,
        )

        if args.command == "backup":
            record = service.create_backup(reason=args.reason)
            _print_result("BACKUP_VALID", backup=_record_payload(record))
            return 0

        if args.command == "verify":
            record = service.verify_backup(args.backup_path)
            _print_result("BACKUP_VALID", backup=_record_payload(record))
            return 0

        try:
            mutex = StationMutex(args.station_id).acquire()
        except InstanceAlreadyRunning:
            _print_result(
                "STATION_ACTIVE",
                station_id=args.station_id,
                command=args.command,
            )
            return STATION_ACTIVE_EXIT_CODE

        if args.command == "migrate":
            report = migrate_sqlite_database(
                database_path=database_path,
                station_id=args.station_id,
                backup_dir=paths.backups,
            )
            _print_result(
                "MIGRATION_COMPLETE",
                previous_version=report.previous_version,
                current_version=report.current_version,
                applied_versions=list(report.applied_versions),
                backup_path=str(report.backup_path) if report.backup_path else None,
            )
            return 0

        if args.command == "import-legacy":
            source_path = args.source_database.expanduser().resolve()
            if source_path == database_path.expanduser().resolve():
                raise BackupError(
                    "Legacy source and destination database must be different files"
                )

            source_before = inspect_database(source_path)
            if "pesajes" not in source_before.table_counts:
                raise BackupError(
                    "Legacy source is not an EnvaPeru weighing database: "
                    "table pesajes was not found"
                )

            destination_before = None
            if database_path.exists():
                destination_before = inspect_database(database_path)
                if "pesajes" not in destination_before.table_counts:
                    raise BackupError(
                        "Existing destination is not an EnvaPeru weighing database; "
                        "it will not be replaced"
                    )
                has_business_data = any(
                    count > 0
                    for count in destination_before.table_counts.values()
                )
                if has_business_data and not args.replace_existing:
                    raise BackupError(
                        "Destination contains business data. Review both databases "
                        "and rerun with --replace-existing only when replacement "
                        "has been explicitly approved"
                    )

            source_service = BackupService(
                database_path=source_path,
                backup_dir=paths.backups,
                station_id=args.station_id,
                retention_count=args.retention_count,
            )
            source_backup = source_service.create_backup(
                reason="legacy-import-source"
            )
            source_after_backup = inspect_database(source_path)
            source_backup_inspection = inspect_database(source_backup.path)
            if source_after_backup != source_before:
                raise BackupError(
                    "Legacy source changed while it was being imported. Stop the "
                    "old station backend and retry; destination was not replaced"
                )
            if (
                source_backup_inspection.table_counts
                != source_before.table_counts
                or source_backup_inspection.max_ids != source_before.max_ids
            ):
                raise BackupError(
                    "Verified source backup does not match legacy business metrics; "
                    "destination was not replaced"
                )

            replaced_database_backup = None
            if destination_before is not None:
                replaced_database_backup = service.create_backup(
                    reason="pre-legacy-import-replaced"
                )

            if destination_before is None:
                if database_path.exists():
                    raise BackupError(
                        "Destination appeared during import preparation. Stop every "
                        "station backend and retry; destination was not replaced"
                    )
            elif inspect_database(database_path) != destination_before:
                raise BackupError(
                    "Destination changed during import preparation. Stop every "
                    "station backend and retry; destination was not replaced"
                )

            source_before_activation = inspect_database(source_path)
            if source_before_activation != source_before:
                raise BackupError(
                    "Legacy source changed before activation. Stop the old station "
                    "backend and retry; destination was not replaced"
                )

            result = service.restore_backup(
                source_backup.path,
                expected_station_id=args.station_id,
            )
            destination_after = inspect_database(database_path)
            source_after_activation = inspect_database(source_path)
            source_unchanged = source_after_activation == source_before
            if (
                destination_after.table_counts.get("pesajes")
                != source_before.table_counts.get("pesajes")
                or destination_after.max_ids.get("pesajes")
                != source_before.max_ids.get("pesajes")
            ):
                raise BackupError(
                    "Activated database does not match legacy pesajes metrics"
                )

            _print_result(
                "LEGACY_IMPORT_COMPLETE",
                source=_inspection_payload(source_before),
                source_unchanged=source_unchanged,
                warning=(
                    None
                    if source_unchanged
                    else "SOURCE_CHANGED_AFTER_VERIFIED_SNAPSHOT"
                ),
                source_backup=_record_payload(source_backup),
                replaced_database_backup=(
                    _record_payload(replaced_database_backup)
                    if replaced_database_backup
                    else None
                ),
                destination=_inspection_payload(destination_after),
                incident_path=(
                    str(result.incident_path) if result.incident_path else None
                ),
                table_counts=result.table_counts,
                max_ids=result.max_ids,
            )
            return 0

        result = service.restore_backup(
            args.backup_path,
            expected_station_id=args.station_id,
        )
        _print_result(
            "RESTORE_COMPLETE",
            database_path=str(result.database_path),
            incident_path=str(result.incident_path) if result.incident_path else None,
            table_counts=result.table_counts,
            max_ids=result.max_ids,
        )
        return 0
    except (BackupError, SchemaMigrationError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "event": "STORAGE_ERROR",
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return STORAGE_ERROR_EXIT_CODE
    finally:
        if mutex is not None:
            mutex.release()


if __name__ == "__main__":
    raise SystemExit(main())
