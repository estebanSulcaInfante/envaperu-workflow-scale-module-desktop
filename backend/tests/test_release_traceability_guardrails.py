import uuid
from datetime import datetime, timezone

import pytest

from app import create_app, db
from app.models.pesaje import Pesaje
from app.models.pesaje_correction_request import PesajeCorrectionRequest


@pytest.fixture
def traceability_app(tmp_path):
    database_path = tmp_path / "station.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "RUNTIME_PROFILE": "RELEASE",
            "SYNC_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "STATION_DATABASE_PATH": str(database_path),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_ID": "TEST-GUARDRAILS-01",
            "MAX_CAPTURE_WEIGHT_KG": 100.0,
        },
        start_workers=False,
    )

    with app.app_context():
        local = Pesaje(
            peso_kg=30.125,
            nro_op="OP-LOCAL-01",
            color="ROJO",
            operador="OPERADOR ORIGINAL",
            capture_id=str(uuid.uuid4()),
            capture_payload_hash="a" * 64,
        )
        acknowledged = Pesaje(
            peso_kg=25.0,
            nro_op="OP-LEGACY-01",
            sincronizado=True,
            fecha_sincronizacion=datetime.now(timezone.utc),
        )
        voided = Pesaje(
            peso_kg=10.0,
            nro_op="OP-VOID-01",
            deleted_at=datetime.now(timezone.utc),
        )
        db.session.add_all([local, acknowledged, voided])
        db.session.commit()
        app.config["TEST_LOCAL_ID"] = local.id
        app.config["TEST_ACKNOWLEDGED_ID"] = acknowledged.id
        app.config["TEST_VOIDED_ID"] = voided.id

    yield app

    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(traceability_app):
    return traceability_app.test_client()


def correction_payload(**overrides):
    payload = {
        "action": "CORRECT",
        "requested_by": "SUPERVISOR TURNO A",
        "reason": "El peso fue asociado a la bolsa equivocada.",
        "evidence_reference": "BITACORA-2026-0717-04",
        "proposed_changes": {
            "peso_kg": "30.250",
            "color": "AZUL",
        },
    }
    payload.update(overrides)
    return payload


def post_correction(client, pesaje_id, request_id, payload=None):
    return client.post(
        f"/api/local/v1/pesajes/{pesaje_id}/corrections",
        json=payload if payload is not None else correction_payload(),
        headers={"Idempotency-Key": request_id},
    )


def test_release_blocks_legacy_and_destructive_mutations(client, traceability_app):
    pesaje_id = traceability_app.config["TEST_LOCAL_ID"]
    cases = [
        (
            client.post(
                "/api/pesajes",
                json={"peso_kg": 99, "nro_op": "OP-BYPASS"},
            ),
            "LEGACY_CAPTURE_DISABLED",
        ),
        (
            client.put(f"/api/pesajes/{pesaje_id}", json={"peso_kg": 99}),
            "DESTRUCTIVE_MUTATION_DISABLED",
        ),
        (
            client.delete(f"/api/pesajes/{pesaje_id}"),
            "DESTRUCTIVE_MUTATION_DISABLED",
        ),
        (
            client.post("/api/pesajes/bulk-delete", json={"ids": [pesaje_id]}),
            "DESTRUCTIVE_MUTATION_DISABLED",
        ),
        (
            client.post(
                "/api/pesajes/marcar-sincronizado",
                json={"ids": [pesaje_id]},
            ),
            "MANUAL_SYNC_DISABLED",
        ),
    ]

    assert [(response.status_code, response.get_json()["code"]) for response, _ in cases] == [
        (403, code) for _response, code in cases
    ]
    with traceability_app.app_context():
        original = db.session.get(Pesaje, pesaje_id)
        assert original.peso_kg == 30.125
        assert original.deleted_at is None
        assert original.sincronizado is False


def test_correction_request_is_append_only_and_idempotent(client, traceability_app):
    pesaje_id = traceability_app.config["TEST_LOCAL_ID"]
    request_id = str(uuid.uuid4())

    first = post_correction(client, pesaje_id, request_id)
    replay = post_correction(client, pesaje_id, request_id.upper())

    assert first.status_code == 201
    assert replay.status_code == 200
    first_data = first.get_json()
    replay_data = replay.get_json()
    assert first_data["idempotent_replay"] is False
    assert replay_data["idempotent_replay"] is True
    assert replay_data["correction_request"]["id"] == first_data["correction_request"]["id"]
    assert first_data["correction_request"]["status"] == "PENDING_LOCAL_REVIEW"
    assert first_data["correction_request"]["source_classification"] == "LOCAL_CAPTURE"

    with traceability_app.app_context():
        original = db.session.get(Pesaje, pesaje_id)
        request_record = PesajeCorrectionRequest.query.one()
        assert original.peso_kg == 30.125
        assert original.color == "ROJO"
        assert original.operador == "OPERADOR ORIGINAL"
        assert request_record.original_snapshot["peso_kg"] == 30.125
        assert request_record.proposed_changes == {
            "color": "AZUL",
            "peso_kg": "30.250",
        }


def test_same_request_id_with_other_payload_conflicts(client, traceability_app):
    pesaje_id = traceability_app.config["TEST_LOCAL_ID"]
    request_id = str(uuid.uuid4())
    assert post_correction(client, pesaje_id, request_id).status_code == 201

    conflict = post_correction(
        client,
        pesaje_id,
        request_id,
        correction_payload(reason="Un motivo diferente para la misma clave."),
    )

    assert conflict.status_code == 409
    assert conflict.get_json()["code"] == "IDEMPOTENCY_CONFLICT"
    with traceability_app.app_context():
        assert PesajeCorrectionRequest.query.count() == 1


def test_acknowledged_legacy_request_never_claims_central_was_corrected(
    client,
    traceability_app,
):
    pesaje_id = traceability_app.config["TEST_ACKNOWLEDGED_ID"]

    response = post_correction(client, pesaje_id, str(uuid.uuid4()))

    assert response.status_code == 201
    correction = response.get_json()["correction_request"]
    assert correction["source_classification"] == "LEGACY_ACKNOWLEDGED_UNVERIFIABLE"
    assert correction["status"] == "REQUIRES_CENTRAL_REVIEW"
    with traceability_app.app_context():
        original = db.session.get(Pesaje, pesaje_id)
        assert original.sincronizado is True
        assert original.peso_kg == 25.0


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_code"),
    [
        (correction_payload(reason=""), 422, "REASON_REQUIRED"),
        (correction_payload(requested_by=""), 422, "REQUESTED_BY_REQUIRED"),
        (correction_payload(action="UNKNOWN"), 422, "INVALID_ACTION"),
        (
            correction_payload(proposed_changes={}),
            422,
            "CHANGES_REQUIRED",
        ),
        (
            correction_payload(proposed_changes={"deleted_at": "now"}),
            422,
            "UNSUPPORTED_CHANGE",
        ),
        (
            correction_payload(proposed_changes={"peso_kg": -1}),
            422,
            "INVALID_WEIGHT",
        ),
        (
            correction_payload(action="VOID", proposed_changes={"peso_kg": 0}),
            422,
            "CHANGES_NOT_ALLOWED",
        ),
    ],
)
def test_correction_request_validates_auditable_payload(
    client,
    traceability_app,
    payload,
    expected_status,
    expected_code,
):
    response = post_correction(
        client,
        traceability_app.config["TEST_LOCAL_ID"],
        str(uuid.uuid4()),
        payload,
    )

    assert response.status_code == expected_status
    assert response.get_json()["code"] == expected_code


def test_voided_legacy_record_cannot_receive_another_void_request(
    client,
    traceability_app,
):
    response = post_correction(
        client,
        traceability_app.config["TEST_VOIDED_ID"],
        str(uuid.uuid4()),
        correction_payload(action="VOID", proposed_changes={}),
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "PESAJE_ALREADY_VOID"


def test_correction_history_is_listed_without_mutating_original(
    client,
    traceability_app,
):
    pesaje_id = traceability_app.config["TEST_LOCAL_ID"]
    assert post_correction(client, pesaje_id, str(uuid.uuid4())).status_code == 201
    assert post_correction(
        client,
        pesaje_id,
        str(uuid.uuid4()),
        correction_payload(action="VOID", proposed_changes={}),
    ).status_code == 201

    response = client.get(f"/api/local/v1/pesajes/{pesaje_id}/corrections")

    assert response.status_code == 200
    assert [item["action"] for item in response.get_json()["items"]] == [
        "CORRECT",
        "VOID",
    ]
    assert response.get_json()["pesaje"]["peso_kg"] == 30.125
