import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app import create_app, db
from app.models.pesaje import Pesaje
from app.services.monitoring_service import MonitoringService, _validate_contract


@pytest.fixture
def progress_app(tmp_path):
    database_path = tmp_path / "station-progress.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "STATION_DATABASE_PATH": str(database_path),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_ID": "PESAJE-PROGRESO-01",
            "STATION_MODE": "MONITORED_LEGACY",
            "CENTRAL_ORIGIN": "http://central.test",
            "TIMEZONE": "America/Lima",
            "PRODUCTION_PROGRESS_DAYS": 31,
        },
        start_workers=False,
    )
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _pesaje(weight, hour, op, ot, mold, color, machine, shift="DIURNO"):
    return Pesaje(
        peso_kg=weight,
        fecha_hora=datetime(2026, 7, 17, hour, 0),
        nro_op=op,
        nro_orden_trabajo=ot,
        molde=mold,
        color=color,
        maquina=machine,
        turno=shift,
        sincronizado=False,
    )


def test_progress_contract_copy_matches_canonical():
    backend_root = Path(__file__).resolve().parents[1]
    workspace_root = Path(__file__).resolve().parents[3]
    for filename in ("contract.schema.json", "examples.json"):
        canonical = (
            workspace_root
            / "contracts"
            / "station-production-progress-v1"
            / filename
        )
        consumer = (
            backend_root
            / "contracts"
            / "station-production-progress-v1"
            / filename
        )
        assert hashlib.sha256(canonical.read_bytes()).digest() == hashlib.sha256(
            consumer.read_bytes()
        ).digest()


def test_snapshot_groups_two_orders_and_is_stable_until_local_data_changes(
    progress_app,
):
    with progress_app.app_context():
        first = _pesaje(
            25.125,
            8,
            "op-1401",
            "ot-0041",
            "TAPA 38 MM",
            "ROJO SOLIDO",
            "ht-250b",
        )
        second = _pesaje(
            25.125,
            9,
            "OP-1401",
            "OT-0041",
            "TAPA 38 MM",
            "ROJO SOLIDO",
            "HT-250B",
        )
        third = _pesaje(
            24.900,
            10,
            "OP-1402",
            "OT-0042",
            "BOTELLA 1 L",
            "NATURAL",
            "SOP-01",
        )
        db.session.add_all([first, second, third])
        db.session.commit()

        service = MonitoringService(
            token_provider=lambda: "unused",
            component_provider=lambda: {},
            now=lambda: datetime(2026, 7, 17, 16, tzinfo=timezone.utc),
        )
        payload = service._build_production_progress_payload(service.now())
        replay = service._build_production_progress_payload(service.now())

        _validate_contract(
            "station-production-progress-v1",
            "request",
            payload,
            "CONTRACT_CONFLICT",
        )
        assert replay == payload
        assert len(payload["rows"]) == 2
        assert [row["op"] for row in payload["rows"]] == ["OP-1401", "OP-1402"]
        assert payload["rows"][0]["bags"] == 2
        assert Decimal(payload["rows"][0]["weight_kg"]) == Decimal("50.250")
        assert payload["rows"][1]["bags"] == 1
        assert Decimal(payload["rows"][1]["weight_kg"]) == Decimal("24.900")

        first.soft_delete()
        db.session.commit()
        corrected = service._build_production_progress_payload(service.now())

        assert corrected["report_id"] != payload["report_id"]
        assert corrected["rows"][0]["bags"] == 1
        assert corrected["rows"][0]["weight_kg"] == "25.125"


def test_snapshot_keeps_unassigned_weighing_visible(progress_app):
    with progress_app.app_context():
        db.session.add(
            _pesaje(30.000, 11, None, None, None, None, None, shift=None)
        )
        db.session.commit()
        service = MonitoringService(
            token_provider=lambda: "unused",
            component_provider=lambda: {},
            now=lambda: datetime(2026, 7, 17, 16, tzinfo=timezone.utc),
        )

        payload = service._build_production_progress_payload(service.now())

        assert payload["rows"][0]["op"] is None
        assert payload["rows"][0]["weight_kg"] == "30.000"
