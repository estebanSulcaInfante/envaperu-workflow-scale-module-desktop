import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine

from app.storage.sqlite import configure_sqlite_engine, database_path_from_engine


LOGGER = logging.getLogger(__name__)
MIGRATION_TABLE = "schema_migrations"


class SchemaMigrationError(RuntimeError):
    pass


class SchemaTooNewError(SchemaMigrationError):
    pass


class SchemaIncompatibleError(SchemaMigrationError):
    pass


class MigrationBackupRequiredError(SchemaMigrationError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: object


@dataclass(frozen=True)
class MigrationReport:
    previous_version: int
    current_version: int
    applied_versions: tuple
    backup_path: Path | None


LEGACY_COLUMNS_V1 = {
    "pesajes": {
        "molde": "VARCHAR(100)",
        "maquina": "VARCHAR(50)",
        "nro_op": "VARCHAR(20)",
        "turno": "VARCHAR(20)",
        "fecha_orden_trabajo": "DATE",
        "nro_orden_trabajo": "VARCHAR(20)",
        "peso_unitario_teorico": "FLOAT",
        "operador": "VARCHAR(100)",
        "color": "VARCHAR(100)",
        "pieza_sku": "VARCHAR(50)",
        "pieza_nombre": "VARCHAR(100)",
        "observaciones": "TEXT",
        "sticker_impreso": "BOOLEAN DEFAULT 0",
        "fecha_impresion": "DATETIME",
        "sincronizado": "BOOLEAN DEFAULT 0",
        "fecha_sincronizacion": "DATETIME",
        "qr_data_original": "VARCHAR(500)",
        "deleted_at": "DATETIME",
    },
    "correlativo_cache": {
        "fecha_reserva": "DATETIME",
        "usado": "BOOLEAN DEFAULT 0",
        "fecha_uso": "DATETIME",
        "nro_op": "VARCHAR(50)",
        "molde": "VARCHAR(100)",
        "maquina": "VARCHAR(50)",
        "turno": "VARCHAR(20)",
        "fecha_ot": "VARCHAR(20)",
        "operador": "VARCHAR(100)",
        "color": "VARCHAR(50)",
        "anulado": "BOOLEAN DEFAULT 0",
        "fecha_anulacion": "DATETIME",
        "motivo_anulacion": "VARCHAR(200)",
    },
    "molde_piezas_cache": {
        "molde_codigo": "VARCHAR(50)",
        "molde_nombre": "VARCHAR(100)",
        "peso_tiro_gr": "FLOAT",
        "tiempo_ciclo_std": "FLOAT",
        "pieza_sku": "VARCHAR(50)",
        "pieza_nombre": "VARCHAR(100)",
        "tipo": "VARCHAR(20)",
        "cavidades": "INTEGER",
        "peso_unitario_gr": "FLOAT",
        "updated_at": "DATETIME",
    },
    "ops_cerradas": {
        "nro_op": "VARCHAR(20)",
        "molde": "VARCHAR(100)",
        "motivo": "VARCHAR(200)",
        "fecha_cierre": "DATETIME",
    },
}

REQUIRED_CORE_COLUMNS = {
    "pesajes": {"id", "peso_kg", "fecha_hora"},
    "correlativo_cache": {"correlativo"},
    "molde_piezas_cache": {"id"},
    "ops_cerradas": {"id"},
}

EXPECTED_COLUMNS = {
    table: set(columns) | REQUIRED_CORE_COLUMNS[table]
    for table, columns in LEGACY_COLUMNS_V1.items()
}
EXPECTED_COLUMNS["pesajes"].add("lote_salida_pieza_color_id")
EXPECTED_COLUMNS["pesajes"].update({"capture_id", "capture_payload_hash"})
EXPECTED_COLUMNS["print_attempts"] = {
    "id",
    "pesaje_id",
    "attempted_at_utc",
    "completed_at_utc",
    "printer_name",
    "result",
    "error_code",
    "error_detail",
}
EXPECTED_COLUMNS["pesaje_correction_requests"] = {
    "id",
    "request_id",
    "request_payload_hash",
    "pesaje_id",
    "requested_at_utc",
    "requested_by",
    "action",
    "reason",
    "evidence_reference",
    "proposed_changes_json",
    "original_snapshot_json",
    "source_classification",
    "status",
}
EXPECTED_COLUMNS["station_identity"] = {
    "station_id",
    "station_code",
    "created_at_utc",
    "provisioned_at_utc",
}
EXPECTED_COLUMNS["station_runtime_state"] = {
    "station_id",
    "boot_id",
    "sequence",
    "started_at_utc",
    "last_attempt_at_utc",
    "last_central_ack_utc",
    "last_heartbeat_id",
    "communication_state",
    "last_error_code",
    "next_heartbeat_seconds",
}


def _quote_identifier(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _table_exists(connection, table):
    return (
        connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).first()
        is not None
    )


def _table_columns(connection, table):
    if not _table_exists(connection, table):
        return set()
    return {
        row[1]
        for row in connection.exec_driver_sql(
            f"PRAGMA table_info({_quote_identifier(table)})"
        ).all()
    }


def _add_missing_columns(connection, table, definitions):
    columns = _table_columns(connection, table)
    missing_core = REQUIRED_CORE_COLUMNS[table] - columns
    if missing_core:
        names = ", ".join(sorted(missing_core))
        raise SchemaIncompatibleError(
            f"Table {table} is missing non-migratable core columns: {names}"
        )

    for column, definition in definitions.items():
        if column in columns:
            continue
        connection.exec_driver_sql(
            f"ALTER TABLE {_quote_identifier(table)} "
            f"ADD COLUMN {_quote_identifier(column)} {definition}"
        )
        columns.add(column)


def _unique_index_exists(connection, table, expected_columns):
    for index_row in connection.exec_driver_sql(
        f"PRAGMA index_list({_quote_identifier(table)})"
    ).all():
        if not index_row[2]:
            continue
        index_name = index_row[1]
        columns = tuple(
            row[2]
            for row in connection.exec_driver_sql(
                f"PRAGMA index_info({_quote_identifier(index_name)})"
            ).all()
        )
        if columns == tuple(expected_columns):
            return True
    return False


def _migration_1_legacy_baseline(connection, metadata):
    metadata.create_all(bind=connection)

    for table, definitions in LEGACY_COLUMNS_V1.items():
        _add_missing_columns(connection, table, definitions)

    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_molde_piezas_cache_molde_codigo "
        "ON molde_piezas_cache (molde_codigo)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_molde_piezas_cache_molde_nombre "
        "ON molde_piezas_cache (molde_nombre)"
    )
    if not _unique_index_exists(
        connection,
        "molde_piezas_cache",
        ("molde_codigo", "pieza_sku"),
    ):
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_molde_pieza_cache "
            "ON molde_piezas_cache (molde_codigo, pieza_sku)"
        )
    if not _unique_index_exists(connection, "ops_cerradas", ("nro_op",)):
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_ops_cerradas_nro_op ON ops_cerradas (nro_op)"
        )


def _migration_2_lote_salida_traceability(connection, _metadata):
    columns = _table_columns(connection, "pesajes")
    if "lote_salida_pieza_color_id" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE pesajes ADD COLUMN lote_salida_pieza_color_id INTEGER"
        )


def _migration_3_idempotent_capture_and_print_attempts(connection, metadata):
    columns = _table_columns(connection, "pesajes")
    if "capture_id" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE pesajes ADD COLUMN capture_id VARCHAR(36)"
        )
    if "capture_payload_hash" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE pesajes ADD COLUMN capture_payload_hash VARCHAR(64)"
        )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pesajes_capture_id "
        "ON pesajes (capture_id)"
    )

    print_attempts = metadata.tables.get("print_attempts")
    if print_attempts is None:
        raise SchemaIncompatibleError("PrintAttempt metadata is not registered")
    print_attempts.create(bind=connection, checkfirst=True)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_print_attempts_pesaje_id "
        "ON print_attempts (pesaje_id)"
    )


def _migration_4_append_only_correction_requests(connection, metadata):
    correction_requests = metadata.tables.get("pesaje_correction_requests")
    if correction_requests is None:
        raise SchemaIncompatibleError(
            "PesajeCorrectionRequest metadata is not registered"
        )
    correction_requests.create(bind=connection, checkfirst=True)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_pesaje_correction_requests_pesaje_id "
        "ON pesaje_correction_requests (pesaje_id)"
    )


def _migration_5_station_monitoring_identity(connection, metadata):
    station_identity = metadata.tables.get("station_identity")
    runtime_state = metadata.tables.get("station_runtime_state")
    if station_identity is None or runtime_state is None:
        raise SchemaIncompatibleError(
            "Station monitoring metadata is not registered"
        )
    station_identity.create(bind=connection, checkfirst=True)
    runtime_state.create(bind=connection, checkfirst=True)


MIGRATIONS = (
    Migration(1, "legacy_baseline", _migration_1_legacy_baseline),
    Migration(2, "lote_salida_pieza_color_traceability", _migration_2_lote_salida_traceability),
    Migration(
        3,
        "idempotent_capture_and_print_attempts",
        _migration_3_idempotent_capture_and_print_attempts,
    ),
    Migration(
        4,
        "append_only_correction_requests",
        _migration_4_append_only_correction_requests,
    ),
    Migration(
        5,
        "station_monitoring_identity",
        _migration_5_station_monitoring_identity,
    ),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def _create_migration_table(connection):
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at_utc TEXT NOT NULL
        )
        """
    )


def _read_applied_migrations(connection):
    if not _table_exists(connection, MIGRATION_TABLE):
        return []
    try:
        return connection.exec_driver_sql(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).all()
    except Exception as exc:
        raise SchemaIncompatibleError(
            "schema_migrations does not have the expected structure"
        ) from exc


def _validate_history(applied):
    if not applied:
        return 0

    current = applied[-1][0]
    if current > LATEST_SCHEMA_VERSION:
        raise SchemaTooNewError(
            f"Database schema v{current} is newer than binary v{LATEST_SCHEMA_VERSION}"
        )

    expected = [(migration.version, migration.name) for migration in MIGRATIONS[:current]]
    actual = [(row[0], row[1]) for row in applied]
    if actual != expected:
        raise SchemaIncompatibleError(
            f"Unexpected migration history: expected {expected}, found {actual}"
        )
    return current


def _validate_current_schema(connection):
    for table, expected in EXPECTED_COLUMNS.items():
        actual = _table_columns(connection, table)
        missing = expected - actual
        if missing:
            names = ", ".join(sorted(missing))
            raise SchemaIncompatibleError(
                f"Schema v{LATEST_SCHEMA_VERSION} table {table} is missing: {names}"
            )

    integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
    if integrity != "ok":
        raise SchemaIncompatibleError(f"SQLite integrity_check failed: {integrity}")


def _file_schema_state(database_path):
    database_path = Path(database_path)
    if not database_path.exists() or database_path.stat().st_size == 0:
        return 0, False

    try:
        with closing(sqlite3.connect(database_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if MIGRATION_TABLE not in tables:
                return 0, bool(tables)
            rows = connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise SchemaIncompatibleError(
            f"Cannot inspect SQLite schema at {database_path}: {exc}"
        ) from exc

    return _validate_history(rows), bool(tables - {MIGRATION_TABLE})


class MigrationManager:
    def __init__(self, engine, metadata, backup_service=None):
        if engine.dialect.name != "sqlite":
            raise SchemaMigrationError("Station migrations require SQLite")
        self.engine = configure_sqlite_engine(engine)
        self.metadata = metadata
        self.backup_service = backup_service
        self.database_path = database_path_from_engine(engine)

    def migrate(self, backup_already_exists=False):
        if self.database_path is not None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            previous_version, has_application_tables = _file_schema_state(
                self.database_path
            )
        else:
            with self.engine.connect() as connection:
                applied = _read_applied_migrations(connection)
                previous_version = _validate_history(applied)
                has_application_tables = any(
                    _table_exists(connection, table) for table in EXPECTED_COLUMNS
                )

        if previous_version > LATEST_SCHEMA_VERSION:
            raise SchemaTooNewError(
                f"Database schema v{previous_version} is newer than binary "
                f"v{LATEST_SCHEMA_VERSION}"
            )

        backup_path = None
        if previous_version < LATEST_SCHEMA_VERSION and has_application_tables:
            if backup_already_exists:
                LOGGER.info(
                    "MIGRATION_BACKUP_REUSED from=%s to=%s",
                    previous_version,
                    LATEST_SCHEMA_VERSION,
                )
            elif self.backup_service is None:
                raise MigrationBackupRequiredError(
                    "An existing station database must be backed up before migration"
                )
            else:
                backup = self.backup_service.create_backup(
                    reason=(
                        f"pre-migration-v{previous_version}-to-"
                        f"v{LATEST_SCHEMA_VERSION}"
                    ),
                    schema_version=previous_version,
                )
                backup_path = backup.path

        applied_versions = []
        for migration in MIGRATIONS:
            if migration.version <= previous_version:
                continue
            LOGGER.info(
                "MIGRATION_START version=%s name=%s",
                migration.version,
                migration.name,
            )
            with self.engine.begin() as connection:
                _create_migration_table(connection)
                migration.apply(connection, self.metadata)
                connection.exec_driver_sql(
                    "INSERT INTO schema_migrations "
                    "(version, name, applied_at_utc) VALUES (?, ?, ?)",
                    (
                        migration.version,
                        migration.name,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            applied_versions.append(migration.version)

        with self.engine.connect() as connection:
            current_version = _validate_history(_read_applied_migrations(connection))
            if current_version != LATEST_SCHEMA_VERSION:
                raise SchemaIncompatibleError(
                    f"Migration stopped at v{current_version}; expected "
                    f"v{LATEST_SCHEMA_VERSION}"
                )
            _validate_current_schema(connection)

        LOGGER.info(
            "MIGRATION_COMPLETE from=%s to=%s applied=%s backup=%s",
            previous_version,
            current_version,
            applied_versions,
            backup_path,
        )
        return MigrationReport(
            previous_version=previous_version,
            current_version=current_version,
            applied_versions=tuple(applied_versions),
            backup_path=backup_path,
        )


def current_schema_version(engine):
    with engine.connect() as connection:
        return _validate_history(_read_applied_migrations(connection))


def migrate_sqlite_database(
    database_path,
    station_id,
    backup_dir,
    backup_already_exists=False,
):
    from app import db
    import app.models  # noqa: F401

    database_path = Path(database_path).expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    configure_sqlite_engine(engine)

    try:
        backup_service = None
        if not backup_already_exists:
            from app.storage.backup import BackupService

            backup_service = BackupService(database_path, backup_dir, station_id)
        return MigrationManager(
            engine,
            db.Model.metadata,
            backup_service=backup_service,
        ).migrate(backup_already_exists=backup_already_exists)
    finally:
        engine.dispose()
