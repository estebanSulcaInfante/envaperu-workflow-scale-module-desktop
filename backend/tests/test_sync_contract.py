import json
import os
from datetime import date, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SYNC_ENABLED"] = "false"
os.environ["TESTING"] = "true"

from app import create_app, db
from app.models.pesaje import Pesaje
from app.services import sync_service as sync_module
from app.services.sync_service import SyncService


pytestmark = pytest.mark.contract

CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contracts" / "sync-pesajes-legacy-v1"


def load_json(filename):
    return json.loads((CONTRACT_DIR / filename).read_text(encoding="utf-8"))


def validate_contract(definition, instance):
    schema = load_json("contract.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema["$defs"][definition]).validate(instance)


@pytest.fixture
def app():
    application = create_app()
    application.config.update(TESTING=True)

    with application.app_context():
        yield application
        db.session.remove()
        db.drop_all()


def build_pesaje():
    return Pesaje(
        peso_kg=12.5,
        fecha_hora=datetime.fromisoformat("2026-07-13T10:30:00-05:00"),
        nro_op="OP-CONTRACT-001",
        turno="DIURNO",
        fecha_orden_trabajo=date.fromisoformat("2026-07-13"),
        nro_orden_trabajo="30001",
        maquina="MAQUINA 1",
        molde="MOLDE CONTRACT",
        color="ROJO",
        operador="OPERADOR CONTRACT",
        pieza_sku="PZ-CONTRACT-ROJO",
        pieza_nombre="PIEZA CONTRACT ROJO",
        qr_data_original="QR-CONTRACT-001",
    )


def test_sync_consumer_emits_legacy_v1_request(app):
    examples = load_json("examples.json")

    with app.app_context():
        pesaje = build_pesaje()
        db.session.add(pesaje)
        db.session.flush()

        payload = {"pesajes": [SyncService()._pesaje_to_sync_payload(pesaje)]}

    validate_contract("request", payload)
    assert payload == examples["request"]


def test_sync_consumer_accepts_legacy_v1_response(app, monkeypatch):
    examples = load_json("examples.json")
    validate_contract("response", examples["response"])

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return examples["response"]

    with app.app_context():
        pesaje = build_pesaje()
        db.session.add(pesaje)
        db.session.commit()

        service = SyncService("http://central.test/api")
        monkeypatch.setattr(service, "check_connectivity", lambda: True)

        def fake_post(url, json, timeout):
            assert url == "http://central.test/api/sync/pesajes"
            assert timeout == 30
            validate_contract("request", json)
            return FakeResponse()

        monkeypatch.setattr(sync_module.requests, "post", fake_post)

        result = service.sync_pesajes([pesaje])
        db.session.refresh(pesaje)

        assert result["success"] is True
        assert result["synced"] == [{"local_id": 1}]
        assert pesaje.sincronizado is True
        assert pesaje.fecha_sincronizacion is not None
