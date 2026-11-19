from decimal import Decimal

import pytest

from mesa_pilot import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "mesa.sqlite3")
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def _state(client):
    response = client.get("/api/mesa/state")
    assert response.status_code == 200
    return response.get_json()


def test_state_seeds_six_demo_mangas_and_keeps_lot_unknown(client):
    state = _state(client)

    assert len(state["units"]) >= 6
    seeded = [unit for unit in state["units"] if unit["code"].startswith("OFDEMO-OT101-M")]
    assert len(seeded) >= 6
    assert {unit["status"] for unit in seeded} == {"available"}
    assert {unit["piece"] for unit in seeded[:3]} == {"TAPA"}
    assert {unit["color"] for unit in seeded[:3]} == {"AZUL"}
    assert len({unit["lot"] for unit in seeded[:3]}) == 3
    assert any(unit["lot"] is None for unit in seeded)
    assert all(unit["origins"] == [] for unit in seeded)
    assert state["receipts"] == []


def test_union_requires_same_piece_and_color_and_reserves_sources(client):
    response = client.post(
        "/api/mesa/unions",
        json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]},
    )

    assert response.status_code == 201
    code = response.get_json()["code"]
    assert code == "UNION-001"
    state = _state(client)
    units = {unit["code"]: unit for unit in state["units"]}

    assert units[code]["status"] == "pending"
    assert units[code]["piece"] == "TAPA"
    assert units[code]["color"] == "AZUL"
    assert units[code]["lot"] is None
    assert units[code]["origins"] == ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]
    assert units["OFDEMO-OT101-M001"]["status"] == "reserved"
    assert units["OFDEMO-OT101-M002"]["status"] == "reserved"


def test_union_replay_returns_exact_same_union_without_new_stock(client):
    payload = {"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]}
    first = client.post("/api/mesa/unions", json=payload)
    replay = client.post("/api/mesa/unions", json={"codes": list(reversed(payload["codes"]))})

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.get_json() == first.get_json()
    assert len(_state(client)["units"]) == 7


def test_union_rejects_incompatible_or_non_available_sources(client):
    incompatible = client.post(
        "/api/mesa/unions",
        json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M004"]},
    )
    assert incompatible.status_code == 409
    assert "pieza" in incompatible.get_json()["error"]

    reserved = client.post(
        "/api/mesa/unions",
        json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]},
    )
    repeated = client.post(
        "/api/mesa/unions",
        json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M003"]},
    )
    assert reserved.status_code == 201
    assert repeated.status_code == 409
    assert "disponibles" in repeated.get_json()["error"]


@pytest.mark.parametrize("net_kg", ["0", "-1", "nan", "inf", "1.2345", "1e2", "1_0", ""])
def test_receive_rejects_invalid_net_weight(client, net_kg):
    create = client.post(
        "/api/mesa/unions",
        json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]},
    )
    code = create.get_json()["code"]

    response = client.post(
        "/api/mesa/receive",
        json={"code": code, "net_kg": net_kg, "request_id": "req-invalid"},
    )

    assert response.status_code == 422
    assert response.get_json().keys() == {"error"}


def test_receive_is_transactional_and_idempotent_without_double_stock(client):
    create = client.post(
        "/api/mesa/unions",
        json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]},
    )
    code = create.get_json()["code"]
    payload = {"code": code, "net_kg": "1.250", "request_id": "req-001"}

    first = client.post("/api/mesa/receive", json=payload)
    replay = client.post("/api/mesa/receive", json=payload)
    conflict = client.post(
        "/api/mesa/receive",
        json={**payload, "net_kg": "1.251"},
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.get_json() == first.get_json()
    assert conflict.status_code == 409
    assert Decimal(str(first.get_json()["net_kg"])) == Decimal("1.250")

    state = _state(client)
    units = {unit["code"]: unit for unit in state["units"]}
    assert units[code]["status"] == "received"
    assert units["OFDEMO-OT101-M001"]["status"] == "received"
    assert units["OFDEMO-OT101-M002"]["status"] == "received"
    assert len(state["receipts"]) == 1


def test_receive_available_seed_is_idempotent_and_blocks_reuse(client):
    payload = {"code": "OFDEMO-OT101-M003", "net_kg": "0.750", "request_id": "single-001"}

    first = client.post("/api/mesa/receive", json=payload)
    replay = client.post("/api/mesa/receive", json=payload)
    second_request = client.post(
        "/api/mesa/receive",
        json={**payload, "request_id": "single-002"},
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.get_json() == first.get_json()
    assert second_request.status_code == 409
    state = _state(client)
    assert [receipt["code"] for receipt in state["receipts"]] == [payload["code"]]
    assert next(unit for unit in state["units"] if unit["code"] == payload["code"])["status"] == "received"


def test_receive_rejects_reserved_source_before_union_receipt(client):
    created = client.post(
        "/api/mesa/unions",
        json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]},
    )
    response = client.post(
        "/api/mesa/receive",
        json={"code": "OFDEMO-OT101-M001", "net_kg": "1", "request_id": "reserved-001"},
    )

    assert created.status_code == 201
    assert response.status_code == 409


def test_receive_survives_app_reload_and_request_id_replay(client, tmp_path):
    db_path = tmp_path / "reload.sqlite3"
    app = create_app(db_path)
    app.config.update(TESTING=True)
    with app.test_client() as first_client:
        code = first_client.post(
            "/api/mesa/unions",
            json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]},
        ).get_json()["code"]
        created = first_client.post(
            "/api/mesa/receive",
            json={"code": code, "net_kg": "2.5", "request_id": "persisted-1"},
        ).get_json()

    reloaded = create_app(db_path)
    reloaded.config.update(TESTING=True)
    with reloaded.test_client() as second_client:
        replay = second_client.post(
            "/api/mesa/receive",
            json={"code": code, "net_kg": "2.500", "request_id": "persisted-1"},
        )
        state = second_client.get("/api/mesa/state").get_json()

    assert replay.status_code == 200
    assert replay.get_json() == created
    assert len(state["receipts"]) == 1


def test_qr_endpoint_returns_printable_svg_for_known_code(client):
    response = client.get("/api/mesa/qr/OFDEMO-OT101-M001.svg")

    assert response.status_code == 200
    assert response.content_type.startswith("image/svg+xml")
    assert response.data.startswith(b"<?xml") or b"<svg" in response.data


def test_mutations_reject_non_local_browser_origin(client):
    response = client.post(
        "/api/mesa/unions",
        json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]},
        headers={"Origin": "https://example.invalid"},
    )

    assert response.status_code == 403
    assert response.get_json() == {"error": "Solo se permiten escrituras desde el equipo local"}


def test_mutations_allow_loopback_browser_origin(client):
    response = client.post(
        "/api/mesa/receive",
        json={"code": "OFDEMO-OT101-M003", "net_kg": "0.500", "request_id": "loopback-001"},
        headers={"Origin": "http://127.0.0.1:5196"},
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/mesa/unions", None),
        ("/api/mesa/unions", {"codes": ["OFDEMO-OT101-M001"]}),
        ("/api/mesa/receive", {"code": "no-existe", "net_kg": "1", "request_id": "x"}),
    ],
)
def test_mutation_errors_are_spanish_json(client, path, payload):
    response = client.post(path, json=payload)

    assert 400 <= response.status_code < 500
    assert response.get_json().keys() == {"error"}
    assert response.get_json()["error"]
