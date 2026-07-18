import json
import sqlite3
from contextlib import closing

import pytest

from app import create_app, db
from app.storage.migrations import LATEST_SCHEMA_VERSION, SchemaTooNewError
from app.storage.paths import StationPaths


def _database_uri(path):
    return f"sqlite:///{path.as_posix()}"


def _create_test_app(database_path, backup_dir, station_id="TEST-STORAGE-01"):
    return create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": _database_uri(database_path),
            "STATION_DATABASE_PATH": str(database_path),
            "STATION_BACKUP_DIR": str(backup_dir),
            "STATION_ID": station_id,
        },
        start_workers=False,
    )


def _dispose_app(app):
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def test_programdata_layout_separates_runtime_data_from_release(tmp_path):
    paths = StationPaths.from_environment({"PROGRAMDATA": str(tmp_path)})

    assert paths.root == tmp_path / "EnvaPeru" / "Pesaje"
    assert paths.database == paths.root / "data" / "pesajes.db"

    paths.ensure_layout()

    assert paths.config.is_dir()
    assert paths.secrets.is_dir()
    assert paths.data.is_dir()
    assert paths.backups.is_dir()
    assert paths.logs.is_dir()
    assert paths.run.is_dir()


def test_sqlite_pragmas_and_versioned_schema_are_applied(tmp_path):
    database_path = tmp_path / "data" / "pesajes.db"
    app = _create_test_app(database_path, tmp_path / "backups")

    try:
        with app.app_context():
            pragmas = {
                "foreign_keys": db.session.execute(
                    db.text("PRAGMA foreign_keys")
                ).scalar_one(),
                "journal_mode": db.session.execute(
                    db.text("PRAGMA journal_mode")
                ).scalar_one(),
                "synchronous": db.session.execute(
                    db.text("PRAGMA synchronous")
                ).scalar_one(),
                "busy_timeout": db.session.execute(
                    db.text("PRAGMA busy_timeout")
                ).scalar_one(),
            }
            versions = db.session.execute(
                db.text("SELECT version FROM schema_migrations ORDER BY version")
            ).scalars().all()
            pesaje_columns = {
                row[1]
                for row in db.session.execute(
                    db.text("PRAGMA table_info(pesajes)")
                ).all()
            }
            print_attempts_exists = db.session.execute(
                db.text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'print_attempts'"
                )
            ).scalar_one()
            correction_requests_exists = db.session.execute(
                db.text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' "
                    "AND name = 'pesaje_correction_requests'"
                )
            ).scalar_one()
            station_identity_exists = db.session.execute(
                db.text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'station_identity'"
                )
            ).scalar_one()
            runtime_state_exists = db.session.execute(
                db.text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'station_runtime_state'"
                )
            ).scalar_one()

        assert pragmas == {
            "foreign_keys": 1,
            "journal_mode": "wal",
            "synchronous": 2,
            "busy_timeout": 5000,
        }
        assert versions == list(range(1, LATEST_SCHEMA_VERSION + 1))
        assert "lote_salida_pieza_color_id" in pesaje_columns
        assert "capture_id" in pesaje_columns
        assert "capture_payload_hash" in pesaje_columns
        assert print_attempts_exists == 1
        assert correction_requests_exists == 1
        assert station_identity_exists == 1
        assert runtime_state_exists == 1
        assert app.config["SCHEMA_VERSION"] == LATEST_SCHEMA_VERSION
        assert list((tmp_path / "backups").glob("*.db")) == []
    finally:
        _dispose_app(app)


def test_legacy_database_is_backed_up_once_and_migrated_without_losing_rows(
    tmp_path,
):
    database_path = tmp_path / "data" / "pesajes.db"
    database_path.parent.mkdir(parents=True)
    backup_dir = tmp_path / "backups"

    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE pesajes (
                id INTEGER PRIMARY KEY,
                peso_kg FLOAT NOT NULL,
                fecha_hora DATETIME NOT NULL,
                observaciones TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO pesajes (id, peso_kg, fecha_hora, observaciones) "
            "VALUES (41, 30.0, '2026-07-17 09:30:00', 'merma molida')"
        )
        connection.execute(
            """
            CREATE TABLE correlativo_cache (
                correlativo INTEGER PRIMARY KEY,
                usado BOOLEAN DEFAULT 0
            )
            """
        )
        connection.execute(
            "INSERT INTO correlativo_cache (correlativo, usado) VALUES (30041, 0)"
        )

    app = _create_test_app(database_path, backup_dir, "PESAJE-LEGACY-01")
    try:
        with app.app_context():
            row = db.session.execute(
                db.text(
                    "SELECT id, peso_kg, observaciones FROM pesajes WHERE id = 41"
                )
            ).one()
            columns = {
                item[1]
                for item in db.session.execute(
                    db.text("PRAGMA table_info(pesajes)")
                ).all()
            }
            versions = db.session.execute(
                db.text("SELECT version FROM schema_migrations ORDER BY version")
            ).scalars().all()

        assert tuple(row) == (41, 30.0, "merma molida")
        assert "lote_salida_pieza_color_id" in columns
        assert "deleted_at" in columns
        assert versions == list(range(1, LATEST_SCHEMA_VERSION + 1))
    finally:
        _dispose_app(app)

    backups_after_first_start = sorted(backup_dir.glob("*.db"))
    assert len(backups_after_first_start) == 1
    assert "PESAJE-LEGACY-01" in backups_after_first_start[0].name
    assert "schema-v0" in backups_after_first_start[0].name

    manifest_path = backups_after_first_start[0].with_suffix(".json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["result"] == "VALID"
    assert manifest["integrity_check"] == "ok"
    assert manifest["sha256"]
    assert manifest["size_bytes"] > 0

    second_app = _create_test_app(database_path, backup_dir, "PESAJE-LEGACY-01")
    _dispose_app(second_app)

    assert sorted(backup_dir.glob("*.db")) == backups_after_first_start


def test_schema_v2_is_backed_up_and_upgraded_through_current_schema(tmp_path):
    database_path = tmp_path / "data" / "pesajes.db"
    backup_dir = tmp_path / "backups"

    initial_app = _create_test_app(database_path, backup_dir, "PESAJE-V2-01")
    _dispose_app(initial_app)

    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            "INSERT INTO pesajes (id, peso_kg, fecha_hora, nro_op) "
            "VALUES (52, 25.5, '2026-07-17 10:15:00', 'OP-00052')"
        )
        connection.execute("DROP TABLE print_attempts")
        connection.execute("DROP TABLE pesaje_correction_requests")
        connection.execute("DROP TABLE station_runtime_state")
        connection.execute("DROP TABLE station_identity")
        connection.execute("DROP INDEX uq_pesajes_capture_id")
        v2_columns = [
            row[1]
            for row in connection.execute("PRAGMA table_info(pesajes)").fetchall()
            if row[1] not in {"capture_id", "capture_payload_hash"}
        ]
        selected_columns = ", ".join(f'"{column}"' for column in v2_columns)
        connection.execute(
            f"CREATE TABLE pesajes_v2 AS SELECT {selected_columns} FROM pesajes"
        )
        connection.execute("DROP TABLE pesajes")
        connection.execute("ALTER TABLE pesajes_v2 RENAME TO pesajes")
        connection.execute("DELETE FROM schema_migrations WHERE version >= 3")

    upgraded_app = _create_test_app(database_path, backup_dir, "PESAJE-V2-01")
    try:
        with upgraded_app.app_context():
            row = db.session.execute(
                db.text("SELECT peso_kg, nro_op FROM pesajes WHERE id = 52")
            ).one()
            versions = db.session.execute(
                db.text("SELECT version FROM schema_migrations ORDER BY version")
            ).scalars().all()
            columns = {
                item[1]
                for item in db.session.execute(
                    db.text("PRAGMA table_info(pesajes)")
                ).all()
            }

        assert tuple(row) == (25.5, "OP-00052")
        assert versions == list(range(1, LATEST_SCHEMA_VERSION + 1))
        assert {"capture_id", "capture_payload_hash"} <= columns
    finally:
        _dispose_app(upgraded_app)

    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    assert "schema-v2" in backups[0].name


def test_schema_v3_is_backed_up_before_adding_correction_requests(tmp_path):
    database_path = tmp_path / "data" / "pesajes.db"
    backup_dir = tmp_path / "backups"

    initial_app = _create_test_app(database_path, backup_dir, "PESAJE-V3-01")
    _dispose_app(initial_app)

    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            "INSERT INTO pesajes (id, peso_kg, fecha_hora, nro_op) "
            "VALUES (63, 31.125, '2026-07-17 11:15:00', 'OP-00063')"
        )
        connection.execute("DROP TABLE pesaje_correction_requests")
        connection.execute("DROP TABLE station_runtime_state")
        connection.execute("DROP TABLE station_identity")
        connection.execute("DELETE FROM schema_migrations WHERE version >= 4")

    upgraded_app = _create_test_app(database_path, backup_dir, "PESAJE-V3-01")
    try:
        with upgraded_app.app_context():
            row = db.session.execute(
                db.text("SELECT peso_kg, nro_op FROM pesajes WHERE id = 63")
            ).one()
            version = db.session.execute(
                db.text("SELECT MAX(version) FROM schema_migrations")
            ).scalar_one()
            correction_table = db.session.execute(
                db.text(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'pesaje_correction_requests'"
                )
            ).scalar_one()

        assert tuple(row) == (31.125, "OP-00063")
        assert version == LATEST_SCHEMA_VERSION
        assert correction_table == 1
    finally:
        _dispose_app(upgraded_app)

    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    assert "schema-v3" in backups[0].name


def test_schema_v4_is_backed_up_before_adding_station_identity(tmp_path):
    database_path = tmp_path / "data" / "pesajes.db"
    backup_dir = tmp_path / "backups"

    initial_app = _create_test_app(database_path, backup_dir, "PESAJE-V4-01")
    _dispose_app(initial_app)

    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("DROP TABLE station_runtime_state")
        connection.execute("DROP TABLE station_identity")
        connection.execute("DELETE FROM schema_migrations WHERE version = 5")

    upgraded_app = _create_test_app(database_path, backup_dir, "PESAJE-V4-01")
    try:
        with upgraded_app.app_context():
            version = db.session.execute(
                db.text("SELECT MAX(version) FROM schema_migrations")
            ).scalar_one()
            identity = db.session.execute(
                db.text(
                    "SELECT station_id, station_code FROM station_identity"
                )
            ).one()
            runtime = db.session.execute(
                db.text(
                    "SELECT boot_id, sequence FROM station_runtime_state"
                )
            ).one()

        assert version == LATEST_SCHEMA_VERSION
        assert identity.station_code == "PESAJE-V4-01"
        assert len(identity.station_id) == 36
        assert len(runtime.boot_id) == 36
        assert runtime.sequence == 0
    finally:
        _dispose_app(upgraded_app)

    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    assert "schema-v4" in backups[0].name


def test_database_newer_than_binary_is_rejected_before_capture(tmp_path):
    database_path = tmp_path / "future.db"
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at_utc TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at_utc) "
            "VALUES (?, 'future', '2026-07-17T00:00:00Z')",
            (LATEST_SCHEMA_VERSION + 1,),
        )

    with pytest.raises(SchemaTooNewError):
        _create_test_app(database_path, tmp_path / "backups")
