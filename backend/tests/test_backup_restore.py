import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import create_app, db
from app.models.pesaje import Pesaje
from app.storage.backup import (
    BackupService,
    BackupStationMismatch,
    BackupVerificationError,
    compare_operational_state,
    inspect_database,
)
from app.runtime.single_instance import StationMutex
from station_storage import STATION_ACTIVE_EXIT_CODE, main as storage_main
from station_storage import OPERATIONAL_DELTA_EXIT_CODE, STORAGE_ERROR_EXIT_CODE


def _database_uri(path):
    return f"sqlite:///{path.as_posix()}"


def _create_database(database_path, backup_dir, station_id):
    app = create_app(
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
    with app.app_context():
        db.session.add(
            Pesaje(
                id=7,
                peso_kg=12.5,
                nro_op="OP-RESTORE-01",
                observaciones="backup original",
            )
        )
        db.session.commit()
        db.session.remove()
        db.engine.dispose()


def _read_weight(database_path, row_id=7):
    with closing(sqlite3.connect(database_path)) as connection:
        return connection.execute(
            "SELECT peso_kg FROM pesajes WHERE id = ?",
            (row_id,),
        ).fetchone()[0]


def _create_legacy_database(database_path, *, row_id=41, weight=30.0):
    database_path.parent.mkdir(parents=True, exist_ok=True)
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
            "VALUES (?, ?, '2026-07-18 08:00:00', 'legacy planta')",
            (row_id, weight),
        )


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_logical_fingerprint_detects_committed_wal_only_update(tmp_path):
    database_path = tmp_path / "wal-evidence.db"
    writer = sqlite3.connect(database_path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT)")
        writer.execute("INSERT INTO evidence (id, value) VALUES (1, 'before')")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        before = inspect_database(database_path)
        writer.execute("UPDATE evidence SET value = 'after' WHERE id = 1")
        writer.commit()
        after = inspect_database(database_path)

        assert before.sha256 == after.sha256
        assert before.table_counts == after.table_counts
        assert before.max_ids == after.max_ids
        assert before.logical_sha256 != after.logical_sha256
    finally:
        writer.close()


def test_operational_fingerprints_detect_updates_without_count_deltas(tmp_path):
    station_id = "PESAJE-ROLLBACK-GUARD-01"
    database_path = tmp_path / "data" / "pesajes.db"
    backup_dir = tmp_path / "backups"
    _create_database(database_path, backup_dir, station_id)
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            "INSERT INTO print_attempts "
            "(id, pesaje_id, attempted_at_utc, result) "
            "VALUES (1, 7, '2026-08-27 12:00:00', 'PENDING')"
        )
        connection.execute(
            "INSERT INTO pesaje_correction_requests "
            "(id, request_id, request_payload_hash, pesaje_id, requested_at_utc, "
            "requested_by, action, reason, proposed_changes_json, "
            "original_snapshot_json, source_classification, status) "
            "VALUES (1, ?, ?, 7, '2026-08-27 12:01:00', 'qa', 'CORRECT', "
            "'test', '{}', '{}', 'LOCAL_CAPTURE', 'PENDING_LOCAL_REVIEW')",
            ("11111111-1111-4111-8111-111111111111", "a" * 64),
        )
        connection.execute(
            "INSERT INTO scm_label_print_attempt "
            "(id, print_job_id, label_id, payload_hash, attempted_at_utc, result) "
            "VALUES (1, ?, ?, ?, '2026-08-27 12:02:00', 'PENDING')",
            (
                "22222222-2222-4222-8222-222222222222",
                "33333333-3333-4333-8333-333333333333",
                "b" * 64,
            ),
        )
        connection.execute(
            "INSERT INTO correlativo_cache "
            "(correlativo, fecha_reserva, usado, anulado) "
            "VALUES (9001, '2026-08-27 12:03:00', 0, 0)"
        )
        connection.execute(
            "INSERT INTO molde_piezas_cache "
            "(id, molde_codigo, pieza_sku, updated_at) "
            "VALUES (1, 'M-01', 'P-01', '2026-08-27 12:04:00')"
        )
        connection.execute(
            "INSERT INTO ops_cerradas "
            "(id, nro_op, fecha_cierre) "
            "VALUES (1, 'OP-01', '2026-08-27 12:05:00')"
        )

    baseline = BackupService(
        database_path,
        backup_dir,
        station_id,
    ).create_backup(reason="pre-validation")
    reference = inspect_database(baseline.path)

    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            "UPDATE pesajes SET sincronizado = 1 WHERE id = 7"
        )
        connection.execute(
            "UPDATE print_attempts SET result = 'SUCCEEDED' WHERE id = 1"
        )
        connection.execute(
            "UPDATE pesaje_correction_requests SET status = 'REQUIRES_CENTRAL_REVIEW' "
            "WHERE id = 1"
        )
        connection.execute(
            "UPDATE scm_label_print_attempt SET result = 'IMPRESA' WHERE id = 1"
        )
        connection.execute(
            "UPDATE correlativo_cache SET usado = 1 WHERE correlativo = 9001"
        )
        connection.execute(
            "UPDATE molde_piezas_cache SET pieza_sku = 'P-02' WHERE id = 1"
        )
        connection.execute(
            "UPDATE ops_cerradas SET motivo = 'turno' WHERE id = 1"
        )

    current = inspect_database(database_path)
    deltas = compare_operational_state(current, reference)

    assert current.table_counts == reference.table_counts
    assert current.max_ids == reference.max_ids
    assert set(deltas) == {
        "pesajes",
        "correlativo_cache",
        "molde_piezas_cache",
        "ops_cerradas",
        "print_attempts",
        "pesaje_correction_requests",
        "scm_label_print_attempt",
    }

    exit_code = storage_main(
        [
            "--data-root",
            str(tmp_path),
            "--station-id",
            station_id,
            "compare-operational",
            str(baseline.path),
        ]
    )
    assert exit_code == OPERATIONAL_DELTA_EXIT_CODE


def test_backup_has_hash_manifest_integrity_and_default_retention(tmp_path):
    station_id = "PESAJE-PLANTA-01"
    database_path = tmp_path / "data" / "pesajes.db"
    backup_dir = tmp_path / "backups"
    _create_database(database_path, backup_dir, station_id)

    service = BackupService(database_path, backup_dir, station_id)
    record = service.create_backup(reason="manual")
    verified = service.verify_backup(record.path)

    assert service.retention_count == 14
    assert record.path.exists()
    assert record.path.name.startswith(
        "pesajes_PESAJE-PLANTA-01_schema-v"
    )
    assert record.size_bytes == record.path.stat().st_size
    assert len(record.sha256) == 64
    assert verified.sha256 == record.sha256
    assert verified.integrity_check == "ok"

    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["reason"] == "manual"
    assert manifest["result"] == "VALID"
    sidecars = [
        path.name
        for path in backup_dir.iterdir()
        if path.name.endswith(("-wal", "-shm")) or ".tmp" in path.name
    ]
    assert sidecars == []


def test_retention_removes_only_old_valid_backups(tmp_path):
    station_id = "PESAJE-RETENTION-01"
    database_path = tmp_path / "data" / "pesajes.db"
    backup_dir = tmp_path / "backups"
    _create_database(database_path, backup_dir, station_id)
    service = BackupService(
        database_path,
        backup_dir,
        station_id,
        retention_count=3,
    )

    records = [service.create_backup(reason="daily") for _ in range(5)]
    retained = sorted(backup_dir.glob("*.db"))

    assert len(retained) == 3
    assert records[-1].path in retained
    assert records[0].path not in retained
    assert records[-1].manifest_path.exists()


def test_restore_validates_copy_then_preserves_replaced_database(tmp_path):
    station_id = "PESAJE-RESTORE-01"
    database_path = tmp_path / "data" / "pesajes.db"
    backup_dir = tmp_path / "backups"
    _create_database(database_path, backup_dir, station_id)
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(
            "INSERT INTO scm_label_print_attempt "
            "(print_job_id, label_id, payload_hash, attempted_at_utc, result) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "11111111-1111-4111-8111-111111111111",
                "22222222-2222-4222-8222-222222222222",
                "a" * 64,
                "2026-08-27 12:00:00",
                "IMPRESA",
            ),
        )
    service = BackupService(database_path, backup_dir, station_id)
    record = service.create_backup(reason="manual")

    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("UPDATE pesajes SET peso_kg = 99.0 WHERE id = 7")

    result = service.restore_backup(
        record.path,
        expected_station_id=station_id,
    )

    assert _read_weight(database_path) == 12.5
    assert result.incident_path is not None
    assert result.incident_path.exists()
    assert _read_weight(result.incident_path) == 99.0
    assert result.table_counts["pesajes"] == 1
    assert result.table_counts["scm_label_print_attempt"] == 1
    assert result.max_ids["pesajes"] == 7


def test_corrupted_backup_never_replaces_current_database(tmp_path):
    station_id = "PESAJE-CORRUPT-01"
    database_path = tmp_path / "data" / "pesajes.db"
    backup_dir = tmp_path / "backups"
    _create_database(database_path, backup_dir, station_id)
    service = BackupService(database_path, backup_dir, station_id)
    record = service.create_backup(reason="manual")

    record.path.write_bytes(record.path.read_bytes() + b"tampered")
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("UPDATE pesajes SET peso_kg = 77.0 WHERE id = 7")

    with pytest.raises(BackupVerificationError):
        service.restore_backup(record.path, expected_station_id=station_id)

    assert _read_weight(database_path) == 77.0
    assert list(backup_dir.glob("incident-*.db")) == []


def test_restore_rejects_backup_from_another_station(tmp_path):
    database_path = tmp_path / "data" / "pesajes.db"
    backup_dir = tmp_path / "backups"
    _create_database(database_path, backup_dir, "PESAJE-A")
    service = BackupService(database_path, backup_dir, "PESAJE-A")
    record = service.create_backup(reason="manual")

    with pytest.raises(BackupStationMismatch):
        service.restore_backup(record.path, expected_station_id="PESAJE-B")


def test_restore_command_is_blocked_while_station_mutex_is_active(tmp_path):
    station_id = "PESAJE-ACTIVE-01"
    database_path = tmp_path / "data" / "pesajes.db"
    backup_dir = tmp_path / "backups"
    _create_database(database_path, backup_dir, station_id)
    record = BackupService(
        database_path,
        backup_dir,
        station_id,
    ).create_backup(reason="manual")

    mutex = StationMutex(station_id).acquire()
    try:
        exit_code = storage_main(
            [
                "--data-root",
                str(tmp_path),
                "--station-id",
                station_id,
                "restore",
                str(record.path),
            ]
        )
    finally:
        mutex.release()

    assert exit_code == STATION_ACTIVE_EXIT_CODE
    assert _read_weight(database_path) == 12.5


def test_import_legacy_preserves_source_and_activates_verified_migration(
    tmp_path,
    capsys,
):
    station_id = "PESAJE-IMPORT-01"
    source = tmp_path / "legacy" / "pesajes.db"
    data_root = tmp_path / "program-data"
    destination = data_root / "data" / "pesajes.db"
    _create_legacy_database(source, row_id=41, weight=30.0)
    source_hash = _sha256(source)

    exit_code = storage_main(
        [
            "--data-root",
            str(data_root),
            "--station-id",
            station_id,
            "import-legacy",
            str(source),
        ]
    )

    assert exit_code == 0
    assert _sha256(source) == source_hash
    assert _read_weight(destination, row_id=41) == 30.0
    with closing(sqlite3.connect(destination)) as connection:
        current_version = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0]
    assert current_version >= 1

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["event"] == "LEGACY_IMPORT_COMPLETE"
    assert payload["source"]["sha256"] == source_hash
    assert payload["source"]["integrity_check"] == "ok"
    assert payload["source_backup"]["sha256"]
    assert payload["destination"]["integrity_check"] == "ok"
    assert payload["table_counts"]["pesajes"] == 1
    assert payload["max_ids"]["pesajes"] == 41
    assert Path(payload["source_backup"]["path"]).exists()
    assert Path(payload["source_backup"]["manifest_path"]).exists()


def test_import_legacy_refuses_nonempty_destination_without_explicit_replace(
    tmp_path,
    capsys,
):
    station_id = "PESAJE-IMPORT-EXISTING-01"
    source = tmp_path / "legacy" / "pesajes.db"
    data_root = tmp_path / "program-data"
    destination = data_root / "data" / "pesajes.db"
    _create_legacy_database(source, row_id=41, weight=30.0)
    _create_database(destination, data_root / "backups", station_id)

    refused = storage_main(
        [
            "--data-root",
            str(data_root),
            "--station-id",
            station_id,
            "import-legacy",
            str(source),
        ]
    )

    assert refused == STORAGE_ERROR_EXIT_CODE
    assert _read_weight(destination) == 12.5
    assert "--replace-existing" in capsys.readouterr().err

    accepted = storage_main(
        [
            "--data-root",
            str(data_root),
            "--station-id",
            station_id,
            "import-legacy",
            str(source),
            "--replace-existing",
        ]
    )

    assert accepted == 0
    assert _read_weight(destination, row_id=41) == 30.0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["replaced_database_backup"] is not None
    assert Path(payload["replaced_database_backup"]["path"]).exists()
    assert Path(payload["incident_path"]).exists()
    assert _read_weight(Path(payload["incident_path"])) == 12.5


def test_import_legacy_corruption_never_replaces_destination(tmp_path, capsys):
    station_id = "PESAJE-IMPORT-CORRUPT-01"
    source = tmp_path / "legacy" / "pesajes.db"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not-a-sqlite-database")
    data_root = tmp_path / "program-data"
    destination = data_root / "data" / "pesajes.db"
    _create_database(destination, data_root / "backups", station_id)

    exit_code = storage_main(
        [
            "--data-root",
            str(data_root),
            "--station-id",
            station_id,
            "import-legacy",
            str(source),
            "--replace-existing",
        ]
    )

    assert exit_code == STORAGE_ERROR_EXIT_CODE
    assert _read_weight(destination) == 12.5
    assert "integrity" in capsys.readouterr().err.lower()


def test_import_legacy_is_blocked_while_station_is_active(tmp_path, capsys):
    station_id = "PESAJE-IMPORT-ACTIVE-01"
    source = tmp_path / "legacy" / "pesajes.db"
    data_root = tmp_path / "program-data"
    _create_legacy_database(source)

    mutex = StationMutex(station_id).acquire()
    try:
        exit_code = storage_main(
            [
                "--data-root",
                str(data_root),
                "--station-id",
                station_id,
                "import-legacy",
                str(source),
            ]
        )
    finally:
        mutex.release()

    assert exit_code == STATION_ACTIVE_EXIT_CODE
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["event"] == "STATION_ACTIVE"
    assert not (data_root / "data" / "pesajes.db").exists()
