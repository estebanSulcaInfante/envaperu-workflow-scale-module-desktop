import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class BackupError(RuntimeError):
    pass


class BackupVerificationError(BackupError):
    pass


class BackupStationMismatch(BackupVerificationError):
    pass


@dataclass(frozen=True)
class BackupRecord:
    path: Path
    manifest_path: Path
    station_id: str
    schema_version: int
    created_at_utc: str
    reason: str
    size_bytes: int
    sha256: str
    integrity_check: str


@dataclass(frozen=True)
class DatabaseInspection:
    path: Path
    size_bytes: int
    sha256: str
    integrity_check: str
    schema_version: int
    table_counts: dict
    max_ids: dict


@dataclass(frozen=True)
class RestoreResult:
    database_path: Path
    incident_path: Path | None
    table_counts: dict
    max_ids: dict


BUSINESS_TABLES = (
    "pesajes",
    "correlativo_cache",
    "molde_piezas_cache",
    "ops_cerradas",
)


def _safe_component(value, fallback):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-.")
    return safe or fallback


def _utc_timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _readonly_connection(path):
    path = Path(path).expanduser().resolve()
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _integrity_check(path):
    try:
        with closing(_readonly_connection(path)) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise BackupVerificationError(
            f"SQLite integrity check could not run for {path}: {exc}"
        ) from exc

    value = result[0] if result else "missing-result"
    if value != "ok":
        raise BackupVerificationError(
            f"SQLite integrity check failed for {path}: {value}"
        )
    return value


def _schema_version(path):
    with closing(_readonly_connection(path)) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='schema_migrations'"
        ).fetchone()
        if table is None:
            return 0
        row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
        return int(row[0])


def _copy_sqlite_database(source_path, destination_path):
    source_path = Path(source_path).expanduser().resolve()
    destination_path = Path(destination_path).expanduser().resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        destination_path.unlink()

    try:
        with closing(_readonly_connection(source_path)) as source:
            with closing(sqlite3.connect(destination_path)) as destination:
                source.backup(destination)
                destination.commit()
                destination.execute("PRAGMA journal_mode=DELETE").fetchone()
                destination.commit()
    except sqlite3.DatabaseError as exc:
        raise BackupError(
            f"SQLite backup failed from {source_path} to {destination_path}: {exc}"
        ) from exc
    finally:
        Path(f"{destination_path}-wal").unlink(missing_ok=True)
        Path(f"{destination_path}-shm").unlink(missing_ok=True)


def _database_metrics(path):
    counts = {}
    max_ids = {}
    with closing(_readonly_connection(path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table in BUSINESS_TABLES:
            if table not in tables:
                continue
            counts[table] = int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            primary_key = "correlativo" if table == "correlativo_cache" else "id"
            columns = {
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            if primary_key in columns:
                value = connection.execute(
                    f'SELECT MAX("{primary_key}") FROM "{table}"'
                ).fetchone()[0]
                max_ids[table] = value
    return counts, max_ids


def inspect_database(database_path):
    database_path = Path(database_path).expanduser().resolve()
    if not database_path.is_file():
        raise BackupVerificationError(
            f"SQLite database does not exist: {database_path}"
        )

    integrity = _integrity_check(database_path)
    try:
        schema_version = _schema_version(database_path)
        table_counts, max_ids = _database_metrics(database_path)
    except sqlite3.DatabaseError as exc:
        raise BackupVerificationError(
            f"SQLite database metadata is invalid for {database_path}: {exc}"
        ) from exc

    return DatabaseInspection(
        path=database_path,
        size_bytes=database_path.stat().st_size,
        sha256=_sha256(database_path),
        integrity_check=integrity,
        schema_version=schema_version,
        table_counts=table_counts,
        max_ids=max_ids,
    )


class BackupService:
    def __init__(
        self,
        database_path,
        backup_dir,
        station_id,
        retention_count=14,
    ):
        self.database_path = Path(database_path).expanduser().resolve()
        self.backup_dir = Path(backup_dir).expanduser().resolve()
        self.station_id = str(station_id)
        self.retention_count = int(retention_count)
        if self.retention_count < 1:
            raise ValueError("retention_count must be at least 1")

    def create_backup(self, reason="manual", schema_version=None):
        if not self.database_path.is_file():
            raise BackupError(f"Station database does not exist: {self.database_path}")

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        station = _safe_component(self.station_id, "unknown-station")
        safe_reason = _safe_component(reason, "manual")
        version = _schema_version(self.database_path) if schema_version is None else int(schema_version)
        created_at = datetime.now(timezone.utc).isoformat()
        timestamp = _utc_timestamp()
        filename = (
            f"pesajes_{station}_schema-v{version}_{timestamp}_{safe_reason}.db"
        )
        final_path = self.backup_dir / filename
        if final_path.exists():
            final_path = self.backup_dir / (
                f"{final_path.stem}_{uuid.uuid4().hex[:8]}.db"
            )
        temporary_path = self.backup_dir / (
            f".{final_path.name}.{uuid.uuid4().hex}.tmp"
        )

        try:
            _copy_sqlite_database(self.database_path, temporary_path)
            integrity = _integrity_check(temporary_path)
            size_bytes = temporary_path.stat().st_size
            digest = _sha256(temporary_path)
            os.replace(temporary_path, final_path)

            manifest_path = final_path.with_suffix(".json")
            manifest = {
                "backup_file": final_path.name,
                "station_id": self.station_id,
                "schema_version": version,
                "created_at_utc": created_at,
                "reason": str(reason),
                "size_bytes": size_bytes,
                "sha256": digest,
                "integrity_check": integrity,
                "result": "VALID",
            }
            manifest_temp = manifest_path.with_name(
                f".{manifest_path.name}.{uuid.uuid4().hex}.tmp"
            )
            manifest_temp.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(manifest_temp, manifest_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            if final_path.exists() and not final_path.with_suffix(".json").exists():
                final_path.unlink(missing_ok=True)
            raise

        record = BackupRecord(
            path=final_path,
            manifest_path=manifest_path,
            station_id=self.station_id,
            schema_version=version,
            created_at_utc=created_at,
            reason=str(reason),
            size_bytes=size_bytes,
            sha256=digest,
            integrity_check=integrity,
        )
        self._apply_retention()
        return record

    def verify_backup(self, backup_path):
        backup_path = Path(backup_path).expanduser().resolve()
        manifest_path = backup_path.with_suffix(".json")
        if not backup_path.is_file():
            raise BackupVerificationError(f"Backup does not exist: {backup_path}")
        if not manifest_path.is_file():
            raise BackupVerificationError(
                f"Backup manifest does not exist: {manifest_path}"
            )

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupVerificationError(
                f"Backup manifest is invalid: {manifest_path}"
            ) from exc

        if manifest.get("result") != "VALID":
            raise BackupVerificationError("Backup manifest is not marked VALID")
        if manifest.get("backup_file") != backup_path.name:
            raise BackupVerificationError("Backup filename does not match its manifest")

        actual_size = backup_path.stat().st_size
        if actual_size != manifest.get("size_bytes"):
            raise BackupVerificationError(
                f"Backup size mismatch: expected {manifest.get('size_bytes')}, "
                f"found {actual_size}"
            )

        actual_hash = _sha256(backup_path)
        if actual_hash != manifest.get("sha256"):
            raise BackupVerificationError("Backup SHA-256 does not match its manifest")

        integrity = _integrity_check(backup_path)
        return BackupRecord(
            path=backup_path,
            manifest_path=manifest_path,
            station_id=str(manifest.get("station_id", "")),
            schema_version=int(manifest.get("schema_version", 0)),
            created_at_utc=str(manifest.get("created_at_utc", "")),
            reason=str(manifest.get("reason", "")),
            size_bytes=actual_size,
            sha256=actual_hash,
            integrity_check=integrity,
        )

    def restore_backup(self, backup_path, expected_station_id):
        record = self.verify_backup(backup_path)
        if record.station_id != str(expected_station_id):
            raise BackupStationMismatch(
                f"Backup belongs to {record.station_id}, expected {expected_station_id}"
            )

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = self.database_path.with_name(
            f".{self.database_path.name}.restore-{uuid.uuid4().hex}.tmp"
        )
        activation_path = self.database_path.with_name(
            f".{self.database_path.name}.activate-{uuid.uuid4().hex}.tmp"
        )

        try:
            source_counts, source_max_ids = _database_metrics(record.path)
            _copy_sqlite_database(record.path, temporary_path)

            from app.storage.migrations import migrate_sqlite_database

            migrate_sqlite_database(
                temporary_path,
                station_id=expected_station_id,
                backup_dir=self.backup_dir,
                backup_already_exists=True,
            )
            _integrity_check(temporary_path)

            # A second SQLite backup consolidates any WAL pages produced by
            # migrations before the file is atomically activated on Windows.
            _copy_sqlite_database(temporary_path, activation_path)
            _integrity_check(activation_path)
            restored_counts, restored_max_ids = _database_metrics(activation_path)

            for table, count in source_counts.items():
                if restored_counts.get(table) != count:
                    raise BackupVerificationError(
                        f"Restore count mismatch for {table}: "
                        f"expected {count}, found {restored_counts.get(table)}"
                    )
            for table, max_id in source_max_ids.items():
                if restored_max_ids.get(table) != max_id:
                    raise BackupVerificationError(
                        f"Restore max ID mismatch for {table}: "
                        f"expected {max_id}, found {restored_max_ids.get(table)}"
                    )

            incident_path = None
            if self.database_path.exists():
                incident_path = self.backup_dir / (
                    f"incident-{_utc_timestamp()}-{self.database_path.name}"
                )
                _copy_sqlite_database(self.database_path, incident_path)
                _integrity_check(incident_path)

            os.replace(activation_path, self.database_path)
            for suffix in ("-wal", "-shm"):
                Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

            return RestoreResult(
                database_path=self.database_path,
                incident_path=incident_path,
                table_counts=restored_counts,
                max_ids=restored_max_ids,
            )
        finally:
            temporary_path.unlink(missing_ok=True)
            activation_path.unlink(missing_ok=True)
            Path(f"{temporary_path}-wal").unlink(missing_ok=True)
            Path(f"{temporary_path}-shm").unlink(missing_ok=True)
            Path(f"{activation_path}-wal").unlink(missing_ok=True)
            Path(f"{activation_path}-shm").unlink(missing_ok=True)

    def _apply_retention(self):
        valid_records = []
        for backup_path in self.backup_dir.glob("pesajes_*.db"):
            try:
                valid_records.append(self.verify_backup(backup_path))
            except BackupVerificationError:
                # Invalid evidence is retained for diagnosis and never counted
                # as one of the valid recovery points.
                continue

        valid_records.sort(key=lambda record: record.created_at_utc, reverse=True)
        for record in valid_records[self.retention_count :]:
            record.path.unlink(missing_ok=True)
            record.manifest_path.unlink(missing_ok=True)
