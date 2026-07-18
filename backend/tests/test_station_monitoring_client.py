import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from app import create_app, db
from app.models.pesaje import Pesaje
from app.models.station_identity import StationIdentity, StationRuntimeState
from app.services.central_api_client import (
    CentralApiClient,
    CentralApiError,
    normalize_central_origin,
)
from app.services.monitoring_service import MonitoringService
from app.runtime.token_store import StationTokenStore


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeCentralClient:
    def __init__(self):
        self.capability_calls = 0
        self.heartbeats = []
        self.progress_reports = []
        self.history_deltas = []
        self.pilot_commands = []
        self.command_acks = []
        self.error = None

    def get_capabilities(self):
        self.capability_calls += 1
        if self.error:
            raise self.error
        return {
            "api_version": "integration-v1",
            "server_time_utc": "2026-07-17T15:00:00+00:00",
            "minimum_station_version": "1.1.0",
            "supported_contracts": {
                "heartbeat": ["station-heartbeat-v1"],
                "catalog": ["station-catalog-v1"],
                "weight_event": [
                    "sync-pesajes-legacy-v1",
                    "station-production-progress-v1",
                    "station-legacy-continuity-v1",
                ],
            },
            "features": {
                "monitoring": True,
                "catalog_snapshot": False,
                "legacy_weight_ingest_enabled": False,
                "remote_hardware_commands": False,
                "pilot_data_commands": True,
            },
        }

    def send_heartbeat(self, station_id, payload):
        if self.error:
            raise self.error
        self.heartbeats.append((station_id, payload))
        return {
            "accepted": True,
            "station_id": station_id,
            "heartbeat_id": payload["heartbeat_id"],
            "received_at_utc": "2026-07-17T15:00:00+00:00",
            "next_heartbeat_seconds": 30,
        }

    def send_production_progress(self, station_id, payload):
        if self.error:
            raise self.error
        self.progress_reports.append((station_id, payload))
        return {
            "accepted": True,
            "station_id": station_id,
            "report_id": payload["report_id"],
            "received_at_utc": "2026-07-17T15:00:01+00:00",
            "rows_applied": len(payload["rows"]),
            "window_start_date": payload["window_start_date"],
            "window_end_date": payload["window_end_date"],
        }

    def get_history_sync_state(self, station_id):
        return {
            "station_id": station_id,
            "initial_import_id": str(uuid.uuid4()),
            "high_watermark": 0,
            "contract_version": "station-legacy-continuity-v1",
        }

    def send_history_delta(self, station_id, payload):
        self.history_deltas.append((station_id, payload))
        return {
            "accepted": True,
            "station_id": station_id,
            "batch_id": payload["batch_id"],
            "rows_received": len(payload["rows"]),
            "rows_created": len(payload["rows"]),
            "high_watermark": max(
                [row["legacy_id"] for row in payload["rows"]], default=0
            ),
            "received_at_utc": "2026-07-17T15:00:00+00:00",
        }

    def get_pilot_commands(self, _station_id):
        return {"items": self.pilot_commands}

    def acknowledge_pilot_command(self, station_id, command_id, payload):
        self.command_acks.append((station_id, command_id, payload))
        return {"command_id": command_id, "station_id": station_id, **payload}


class FakeDpapi:
    @staticmethod
    def CryptProtectData(data, *_args):
        return bytes(value ^ 0xA5 for value in data)

    @staticmethod
    def CryptUnprotectData(data, *_args):
        return None, bytes(value ^ 0xA5 for value in data)


@pytest.fixture
def monitoring_app(tmp_path):
    database_path = tmp_path / "station.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "STATION_DATABASE_PATH": str(database_path),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_ID": "PESAJE-PLANTA-01",
            "STATION_CODE": "PESAJE-PLANTA-01",
            "STATION_MODE": "MONITORED_LEGACY",
            "STATION_APP_VERSION": "1.1.0-pilot",
            "CENTRAL_ORIGIN": "http://central.test",
            "TIMEZONE": "America/Lima",
        },
        start_workers=False,
    )
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _component_provider():
    return {
        "process": "READY",
        "database": "READY",
        "scale": "DISCONNECTED",
        "printer": "NO_VERIFICADO",
        "catalog": "LEGACY_CACHE",
    }


def test_contract_copies_match_workspace_canonical():
    backend_root = Path(__file__).resolve().parents[1]
    workspace_root = Path(__file__).resolve().parents[3]
    for contract in (
        "station-capabilities-v1",
        "station-heartbeat-v1",
        "station-production-progress-v1",
        "station-legacy-history-v1",
        "station-legacy-continuity-v1",
    ):
        for filename in ("contract.schema.json", "examples.json"):
            canonical = workspace_root / "contracts" / contract / filename
            consumer = backend_root / "contracts" / contract / filename
            assert hashlib.sha256(canonical.read_bytes()).digest() == hashlib.sha256(
                consumer.read_bytes()
            ).digest()


def test_station_token_store_never_writes_plaintext(tmp_path, monkeypatch):
    token = "station-secret-token-that-must-not-be-plain"
    path = tmp_path / "secrets" / "station-token.dpapi"
    store = StationTokenStore(path)
    monkeypatch.setattr(store, "_win32crypt", lambda: FakeDpapi)

    store.write(token)

    assert token.encode("utf-8") not in path.read_bytes()
    assert store.read() == token


def test_central_api_client_uses_one_origin_headers_and_timeouts():
    session = FakeSession(
        [
            FakeResponse(200, {"api_version": "integration-v1"}),
            FakeResponse(
                200,
                {
                    "accepted": True,
                    "station_id": "7f99acdd-63e6-4385-bc16-b904d5d8d5ee",
                    "heartbeat_id": "959cd203-4034-49ae-a6bb-881fd8d3f6e1",
                    "received_at_utc": "2026-07-17T15:00:00Z",
                    "next_heartbeat_seconds": 30,
                },
            ),
            FakeResponse(
                200,
                {
                    "accepted": True,
                    "station_id": "7f99acdd-63e6-4385-bc16-b904d5d8d5ee",
                    "report_id": "e6c3a99f-4b98-5b8e-bdd1-3990f0ee22dd",
                    "received_at_utc": "2026-07-17T15:00:01Z",
                    "rows_applied": 2,
                    "window_start_date": "2026-06-17",
                    "window_end_date": "2026-07-17",
                },
            ),
        ]
    )
    client = CentralApiClient(
        origin="https://central.envaperu.test",
        token="secret-station-token",
        station_version="1.1.0-pilot",
        session=session,
    )

    client.get_capabilities()
    client.send_heartbeat(
        "7f99acdd-63e6-4385-bc16-b904d5d8d5ee",
        {"heartbeat_id": "959cd203-4034-49ae-a6bb-881fd8d3f6e1"},
    )
    client.send_production_progress(
        "7f99acdd-63e6-4385-bc16-b904d5d8d5ee",
        {"report_id": "e6c3a99f-4b98-5b8e-bdd1-3990f0ee22dd"},
    )

    capability_call, heartbeat_call, progress_call = session.calls
    assert capability_call[0:2] == (
        "GET",
        "https://central.envaperu.test/api/integration/v1/capabilities",
    )
    assert heartbeat_call[0:2] == (
        "PUT",
        "https://central.envaperu.test/api/integration/v1/stations/"
        "7f99acdd-63e6-4385-bc16-b904d5d8d5ee/heartbeat",
    )
    assert capability_call[2]["timeout"] == (3.0, 30.0)
    assert heartbeat_call[2]["timeout"] == (3.0, 5.0)
    assert progress_call[2]["timeout"] == (3.0, 5.0)
    for _, _, kwargs in session.calls:
        assert kwargs["headers"]["Authorization"] == "Bearer secret-station-token"
        assert uuid.UUID(kwargs["headers"]["X-Correlation-Id"])
    assert (
        heartbeat_call[2]["headers"]["Idempotency-Key"]
        == "959cd203-4034-49ae-a6bb-881fd8d3f6e1"
    )
    assert progress_call[0:2] == (
        "PUT",
        "https://central.envaperu.test/api/integration/v1/stations/"
        "7f99acdd-63e6-4385-bc16-b904d5d8d5ee/production-progress",
    )
    assert (
        progress_call[2]["headers"]["Idempotency-Key"]
        == "e6c3a99f-4b98-5b8e-bdd1-3990f0ee22dd"
    )


def test_remote_http_requires_explicit_insecure_lan_opt_in():
    assert normalize_central_origin("http://127.0.0.1:5000") == (
        "http://127.0.0.1:5000"
    )

    with pytest.raises(ValueError, match="HTTPS"):
        normalize_central_origin("http://192.168.1.50:5000")

    assert normalize_central_origin(
        "http://192.168.1.50:5000",
        allow_insecure=True,
    ) == "http://192.168.1.50:5000"


def test_invalid_central_origin_is_visible_without_crashing_worker(monitoring_app):
    with monitoring_app.app_context():
        service = MonitoringService(
            token_provider=lambda: "test-token",
            component_provider=_component_provider,
        )

        result = service.run_once()

        assert result["state"] == "CENTRAL_CONFIG_ERROR"
        assert StationRuntimeState.query.one().last_error_code == (
            "CENTRAL_CONFIG_ERROR"
        )


@pytest.mark.parametrize(
    ("response", "operation", "expected_state"),
    [
        (requests.Timeout("late"), "capabilities", "CENTRAL_UNREACHABLE"),
        (FakeResponse(401, {"code": "INVALID_TOKEN"}), "capabilities", "AUTH_ERROR"),
        (FakeResponse(404, {}), "capabilities", "CENTRAL_INCOMPATIBLE"),
        (FakeResponse(422, {}), "heartbeat", "PAYLOAD_REJECTED"),
        (FakeResponse(500, {}), "heartbeat", "CENTRAL_ERROR"),
    ],
)
def test_central_api_client_classifies_failures(response, operation, expected_state):
    client = CentralApiClient(
        origin="https://central.envaperu.test",
        token="secret-token",
        station_version="1.1.0",
        session=FakeSession([response]),
    )

    with pytest.raises(CentralApiError) as error:
        if operation == "capabilities":
            client.get_capabilities()
        else:
            client.send_heartbeat(
                "7f99acdd-63e6-4385-bc16-b904d5d8d5ee",
                {"heartbeat_id": str(uuid.uuid4())},
            )

    assert error.value.state == expected_state
    assert "secret-token" not in str(error.value)


def test_legacy_history_uses_extended_read_timeout():
    session = FakeSession([FakeResponse(200, {"status": "RECEIVING"})])
    client = CentralApiClient(
        origin="https://central.envaperu.test",
        token="secret-token",
        station_version="1.1.0",
        session=session,
    )

    client.send_legacy_history_chunk(
        "7f99acdd-63e6-4385-bc16-b904d5d8d5ee",
        "e73e0de4-a456-5e87-a073-21ab05b7addc",
        0,
        {"rows": []},
    )

    assert session.calls[0][2]["timeout"] == (3.0, 120.0)


def test_station_identity_is_uuid_and_survives_restart(monitoring_app):
    database_uri = monitoring_app.config["SQLALCHEMY_DATABASE_URI"]
    database_path = monitoring_app.config["STATION_DATABASE_PATH"]
    backup_dir = monitoring_app.config["STATION_BACKUP_DIR"]

    with monitoring_app.app_context():
        first = StationIdentity.query.one()
        first_station_id = first.station_id
        first_boot_id = StationRuntimeState.query.one().boot_id
        assert uuid.UUID(first_station_id)
        assert first.station_code == "PESAJE-PLANTA-01"

    with monitoring_app.app_context():
        db.session.remove()
        db.engine.dispose()

    restarted = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": database_uri,
            "STATION_DATABASE_PATH": database_path,
            "STATION_BACKUP_DIR": backup_dir,
            "STATION_CODE": "PESAJE-PLANTA-01",
        },
        start_workers=False,
    )
    try:
        with restarted.app_context():
            assert StationIdentity.query.one().station_id == first_station_id
            assert StationRuntimeState.query.one().boot_id != first_boot_id
            assert StationRuntimeState.query.one().sequence == 0
    finally:
        with restarted.app_context():
            db.session.remove()
            db.engine.dispose()


def test_heartbeat_reports_local_legacy_without_secrets(monitoring_app):
    now = datetime(2026, 7, 17, 15, 0, tzinfo=timezone.utc)
    with monitoring_app.app_context():
        db.session.add_all(
            [
                Pesaje(
                    peso_kg=25.125,
                    fecha_hora=datetime(2026, 7, 17, 10, 0),
                    capture_id=str(uuid.uuid4()),
                    nro_op="OP-0041",
                    nro_orden_trabajo="OT-1238",
                    maquina="INY-05",
                    turno="DIURNO",
                    sticker_impreso=True,
                    sincronizado=False,
                ),
                Pesaje(
                    peso_kg=30.0,
                    fecha_hora=datetime(2026, 7, 17, 9, 0),
                    nro_op="OP-0040",
                    sincronizado=False,
                ),
            ]
        )
        db.session.commit()

        fake_client = FakeCentralClient()
        service = MonitoringService(
            client_factory=lambda _token: fake_client,
            token_provider=lambda: "never-serialize-this-token",
            component_provider=_component_provider,
            now=lambda: now,
            monotonic=lambda: 120.0,
        )
        result = service.run_once()

        assert result["state"] == "ONLINE"
        assert fake_client.capability_calls == 1
        station_id, payload = fake_client.heartbeats[0]
        assert uuid.UUID(station_id)
        assert payload["sequence"] == 1
        assert payload["communication"]["legacy_unsynced_count"] == 2
        assert payload["local_summary"]["source"] == "LOCAL_REPORTED_LEGACY"
        assert payload["local_summary"]["bags"] == 2
        assert payload["local_summary"]["weight_kg"] == "55.125"
        assert payload["last_capture"]["weight_kg"] == "25.125"
        assert payload["last_capture"]["print_state"] == "PRINTED"
        assert "never-serialize-this-token" not in str(payload)
        assert "http://central.test" not in str(payload)
        progress_station_id, progress = fake_client.progress_reports[0]
        assert progress_station_id == station_id
        assert len(progress["rows"]) == 2
        assert progress["source"] == "LOCAL_REPORTED_LEGACY"

        runtime = StationRuntimeState.query.one()
        assert runtime.communication_state == "ONLINE"
        assert runtime.sequence == 1
        assert runtime.last_central_ack_utc is not None


def test_pilot_void_command_is_applied_locally_and_acknowledged(monitoring_app):
    with monitoring_app.app_context():
        capture = Pesaje(
            peso_kg=25.0,
            fecha_hora=datetime(2026, 7, 18, 16, 0),
            capture_id=str(uuid.uuid4()),
            nro_op="OP-0213",
            nro_orden_trabajo="025639",
            molde="EMBUDO N1",
            maquina="HT-160B",
            turno="DIA",
        )
        db.session.add(capture)
        db.session.commit()
        capture_id = capture.id

        fake_client = FakeCentralClient()
        command_id = str(uuid.uuid4())
        fake_client.pilot_commands = [
            {
                "command_id": command_id,
                "action": "VOID_CAPTURE",
                "legacy_pesaje_id": capture_id,
                "op": "OP-0213",
                "requested_by": "Jefe de planta",
                "reason": "Pesaje duplicado",
            }
        ]
        service = MonitoringService(
            client_factory=lambda _token: fake_client,
            token_provider=lambda: "test-token",
            component_provider=_component_provider,
        )

        result = service.run_once()

        assert result["state"] == "ONLINE"
        assert db.session.get(Pesaje, capture_id).deleted_at is not None
        station_id = StationIdentity.query.one().station_id
        assert fake_client.command_acks == [
            (
                station_id,
                command_id,
                {
                    "status": "APPLIED",
                    "result": {
                        "deleted_at_local": db.session.get(
                            Pesaje, capture_id
                        ).deleted_at.isoformat(sep=" ")
                    },
                },
            )
        ]
        assert fake_client.progress_reports[0][1]["rows"] == []


def test_central_failure_is_degraded_but_local_capture_remains_ready(monitoring_app):
    fake_client = FakeCentralClient()
    fake_client.error = CentralApiError("CENTRAL_UNREACHABLE", "connection failed")

    with monitoring_app.app_context():
        service = MonitoringService(
            client_factory=lambda _token: fake_client,
            token_provider=lambda: "test-token",
            component_provider=_component_provider,
        )
        result = service.run_once()
        assert result["state"] == "CENTRAL_UNREACHABLE"

    client = monitoring_app.test_client()
    ready = client.get("/api/local/v1/health/ready")
    assert ready.status_code == 200
    assert ready.get_json()["status"] == "READY"
    assert ready.get_json()["central"]["state"] == "CENTRAL_UNREACHABLE"

    capture = client.post(
        "/api/local/v1/pesajes",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "peso_kg": 30.0,
            "nro_op": "OP-OFFLINE-01",
            "fecha_orden_trabajo": "2026-07-17",
        },
    )
    assert capture.status_code == 201


def test_missing_token_is_visible_and_never_calls_central(monitoring_app):
    with monitoring_app.app_context():
        service = MonitoringService(
            client_factory=lambda _token: pytest.fail("central must not be called"),
            token_provider=lambda: None,
            component_provider=_component_provider,
        )
        result = service.run_once()
        assert result["state"] == "CENTRAL_NOT_PROVISIONED"
        assert StationRuntimeState.query.one().communication_state == (
            "CENTRAL_NOT_PROVISIONED"
        )
