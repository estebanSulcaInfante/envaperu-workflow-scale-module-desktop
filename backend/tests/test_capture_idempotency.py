import uuid

import pytest

from app import create_app, db
from app.models.pesaje import Pesaje
from app.models.print_attempt import PrintAttempt


class FakeStickerService:
    def __init__(self, result=True):
        self.result = result
        self.calls = []
        self.error = None

    def print_sticker(self, pesaje):
        self.calls.append(pesaje.id)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def capture_app(tmp_path):
    database_path = tmp_path / "station.db"
    fake_printer = FakeStickerService()
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "STATION_DATABASE_PATH": str(database_path),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_ID": "TEST-CAPTURE-01",
            "MAX_CAPTURE_WEIGHT_KG": 100.0,
            "STICKER_SERVICE": fake_printer,
            "PRINTER_NAME": "FAKE-TSC",
        },
        start_workers=False,
    )
    yield app, fake_printer
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(capture_app):
    return capture_app[0].test_client()


def capture_payload(**overrides):
    payload = {
        "peso_kg": 30.125,
        "nro_op": "OP-1401",
        "molde": "BOTELLA 1L",
        "maquina": "SOPLADORA-01",
        "turno": "DIURNO",
        "fecha_orden_trabajo": "2026-07-17",
        "nro_orden_trabajo": "OT-30041",
        "operador": "OPERADOR TEST",
        "color": "AZUL",
        "pieza_sku": "PZ-BOT-1L-AZUL",
        "pieza_nombre": "BOTELLA 1L AZUL",
        "peso_unitario_teorico": "52.500",
        "qr_data_original": "QR-OP-1401",
    }
    payload.update(overrides)
    return payload


def post_capture(client, capture_id, payload=None):
    return client.post(
        "/api/local/v1/pesajes",
        json=payload or capture_payload(),
        headers={"Idempotency-Key": capture_id},
    )


def test_first_capture_creates_once_and_identical_replay_returns_same_record(
    client,
    capture_app,
):
    capture_id = str(uuid.uuid4())

    first = post_capture(client, capture_id)
    replay = post_capture(
        client,
        capture_id.upper(),
        capture_payload(peso_kg="30.125"),
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert first.get_json()["status"] == "SAVED_PRINT_PENDING"
    assert first.get_json()["idempotent_replay"] is False
    assert replay.get_json()["idempotent_replay"] is True
    assert replay.get_json()["pesaje"]["id"] == first.get_json()["pesaje"]["id"]
    assert replay.get_json()["pesaje"]["capture_id"] == capture_id

    with capture_app[0].app_context():
        assert Pesaje.query.count() == 1


def test_same_capture_id_with_different_payload_returns_conflict(client, capture_app):
    capture_id = str(uuid.uuid4())
    assert post_capture(client, capture_id).status_code == 201

    conflict = post_capture(client, capture_id, capture_payload(peso_kg=31.0))

    assert conflict.status_code == 409
    assert conflict.get_json()["code"] == "IDEMPOTENCY_CONFLICT"
    with capture_app[0].app_context():
        assert Pesaje.query.count() == 1


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (capture_payload(peso_kg=0), "INVALID_WEIGHT"),
        (capture_payload(peso_kg=101), "WEIGHT_LIMIT_EXCEEDED"),
        (capture_payload(nro_op=""), "OP_REQUIRED"),
        (capture_payload(fecha_orden_trabajo="17/07/2026"), "INVALID_DATE"),
        (capture_payload(molde="M" * 101), "STRING_TOO_LONG"),
    ],
)
def test_capture_validates_operational_payload(client, payload, expected_code):
    response = post_capture(client, str(uuid.uuid4()), payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == expected_code


def test_capture_requires_json_and_valid_idempotency_key(client):
    missing_key = client.post("/api/local/v1/pesajes", json=capture_payload())
    invalid_key = post_capture(client, "not-a-uuid")
    invalid_json = client.post(
        "/api/local/v1/pesajes",
        data="not-json",
        headers={
            "Content-Type": "text/plain",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )

    assert missing_key.status_code == 400
    assert missing_key.get_json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert invalid_key.status_code == 400
    assert invalid_key.get_json()["code"] == "INVALID_IDEMPOTENCY_KEY"
    assert invalid_json.status_code == 415
    assert invalid_json.get_json()["code"] == "JSON_REQUIRED"


def test_failed_print_is_recorded_and_retry_does_not_create_another_capture(
    client,
    capture_app,
):
    app, fake_printer = capture_app
    capture_id = str(uuid.uuid4())
    created = post_capture(client, capture_id)
    pesaje_id = created.get_json()["pesaje"]["id"]

    fake_printer.result = False
    failed = client.post(f"/api/local/v1/pesajes/{capture_id}/print")

    assert failed.status_code == 200
    assert failed.get_json()["status"] == "SAVED_PRINT_FAILED"
    assert failed.get_json()["print_attempt"]["result"] == "FAILED"

    fake_printer.result = True
    retried = client.post(f"/api/local/v1/pesajes/{capture_id}/print")

    assert retried.status_code == 200
    assert retried.get_json()["status"] == "SAVED_PRINTED"
    assert retried.get_json()["print_attempt"]["result"] == "SUCCEEDED"
    assert fake_printer.calls == [pesaje_id, pesaje_id]

    with app.app_context():
        pesaje = db.session.get(Pesaje, pesaje_id)
        attempts = PrintAttempt.query.order_by(PrintAttempt.id).all()
        assert Pesaje.query.count() == 1
        assert [attempt.result for attempt in attempts] == ["FAILED", "SUCCEEDED"]
        assert pesaje.sticker_impreso is True
        assert pesaje.fecha_impresion is not None


def test_printer_exception_is_a_durable_failed_attempt(client, capture_app):
    app, fake_printer = capture_app
    capture_id = str(uuid.uuid4())
    assert post_capture(client, capture_id).status_code == 201
    fake_printer.error = RuntimeError("spooler unavailable")

    response = client.post(f"/api/local/v1/pesajes/{capture_id}/print")

    assert response.status_code == 200
    assert response.get_json()["status"] == "SAVED_PRINT_FAILED"
    assert response.get_json()["print_attempt"]["error_code"] == "PRINTER_EXCEPTION"
    with app.app_context():
        attempt = PrintAttempt.query.one()
        assert attempt.result == "FAILED"
        assert "RuntimeError" in attempt.error_detail


def test_printer_initialization_exception_is_recorded(
    client,
    capture_app,
    monkeypatch,
):
    app, _fake_printer = capture_app
    capture_id = str(uuid.uuid4())
    assert post_capture(client, capture_id).status_code == 201
    app.config["STICKER_SERVICE"] = None
    app.config["PRINTER_NAME"] = None

    def fail_initialization():
        raise OSError("printer configuration unavailable")

    monkeypatch.setattr(
        "app.services.print_attempt_service.get_sticker_service",
        fail_initialization,
    )

    response = client.post(f"/api/local/v1/pesajes/{capture_id}/print")

    assert response.status_code == 200
    assert response.get_json()["status"] == "SAVED_PRINT_FAILED"
    with app.app_context():
        attempt = PrintAttempt.query.one()
        assert attempt.result == "FAILED"
        assert attempt.printer_name == app.config["PRINTER_PORT"]
        assert "OSError" in attempt.error_detail
