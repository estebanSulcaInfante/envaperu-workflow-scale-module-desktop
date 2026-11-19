import pytest

from mesa_pilot import create_app
from mesa_inventory import label_data


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "mesa-inventory.sqlite3")
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def inventory_state(client):
    response = client.get("/api/mesa/inventario/estado")
    assert response.status_code == 200
    return response.get_json()


def test_state_exposes_four_zones_catalog_prelabels_and_fixtures(client):
    state = inventory_state(client)

    assert {zone["id"] for zone in state["zonas"]} == {
        "Z-ALMACEN-PIEZAS", "Z-ALMACEN-ARMADO-3P", "Z-ALMACEN-LLANTAS-3P", "Z-ALMACEN-ARMADO-4P",
    }
    assert {article["id"] for article in state["articulos"]} >= {
        "ART-TAPA-AZUL", "ART-ASA-BLANCA", "ART-CUERPO-ROJO",
    }
    mangas = {manga["codigo"]: manga for manga in state["mangas"]}
    assert mangas["INV-DEMO-001"]["estado"] == "DISPONIBLE"
    assert mangas["INV-DEMO-FALTANTE"]["estado"] == "BAJA_COMPROBADA"
    assert mangas["INV-DEMO-NO-RECUPERABLE"]["estado"] == "BAJA_NO_RECUPERABLE"
    assert not any(code.startswith("OFDEMO-OT101-M") for code in mangas)
    assert state["preetiquetas"] == []
    assert all({"id", "zona", "estado", "lecturas"} <= set(item) for item in state["sesiones"])


def test_session_reads_without_stock_can_delete_wrong_read_and_close(client):
    opened = client.post("/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-PIEZAS", "clave": "ses-001"})
    session_id = opened.get_json()["id"]
    before_movements = inventory_state(client)["movimientos"]
    read = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas",
        json={"codigo": "INV-DEMO-001"},
    )
    deleted = client.delete(f"/api/mesa/inventario/sesiones/{session_id}/lecturas/INV-DEMO-001")
    missing = client.delete(f"/api/mesa/inventario/sesiones/{session_id}/lecturas/NO-EXISTE")
    close = client.post(f"/api/mesa/inventario/sesiones/{session_id}/cerrar", json={})
    after_close = client.delete(f"/api/mesa/inventario/sesiones/{session_id}/lecturas/INV-DEMO-001")
    state = inventory_state(client)

    assert opened.status_code == 201
    assert read.status_code == 201
    assert deleted.status_code == 200
    assert missing.status_code == 404
    assert close.status_code == 200
    assert after_close.status_code == 409
    assert state["movimientos"] == before_movements
    session = next(item for item in state["sesiones"] if item["id"] == session_id)
    assert session["estado"] == "CERRADA"
    assert session["lecturas"] == []


def test_same_identity_in_two_sessions_is_explicitly_reported(client):
    first = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-PIEZAS", "clave": "ses-a"}
    ).get_json()["id"]
    second = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-PIEZAS", "clave": "ses-b"}
    ).get_json()["id"]
    first_read = client.post(
        f"/api/mesa/inventario/sesiones/{first}/lecturas", json={"codigo": "INV-DEMO-001"}
    )
    second_read = client.post(
        f"/api/mesa/inventario/sesiones/{second}/lecturas", json={"codigo": "INV-DEMO-001"}
    )

    assert first_read.status_code == 201
    assert second_read.status_code == 201
    assert "otra sesión" in second_read.get_json()["mensaje"]


def test_zone_conflict_returns_stale_zone_and_requires_confirmation(client):
    session_id = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-ARMADO-3P", "clave": "ses-zone"}
    ).get_json()["id"]
    conflict = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas",
        json={"codigo": "INV-DEMO-001", "confirmar_zona": False},
    )
    stale = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas",
        json={"codigo": "INV-DEMO-001", "confirmar_zona": True, "zona_anterior": "Z-ALMACEN-LLANTAS-3P"},
    )
    confirmed = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas",
        json={"codigo": "INV-DEMO-001", "confirmar_zona": True, "zona_anterior": "Z-ALMACEN-PIEZAS"},
    )

    assert conflict.status_code == 409
    assert "INV-DEMO-001 figura en Almacén de piezas general." in conflict.get_json()["error"]
    assert "¿La encontraste en Almacén de armado" in conflict.get_json()["error"]
    assert conflict.get_json()["zona_anterior"] == "Z-ALMACEN-PIEZAS"
    assert stale.status_code == 409
    assert stale.get_json()["zona_anterior"] == "Z-ALMACEN-PIEZAS"
    assert confirmed.status_code == 201
    manga = next(item for item in inventory_state(client)["mangas"] if item["codigo"] == "INV-DEMO-001")
    assert manga["zona"] == "Z-ALMACEN-ARMADO-3P"
    deleted = client.delete(f"/api/mesa/inventario/sesiones/{session_id}/lecturas/INV-DEMO-001")
    restored = next(item for item in inventory_state(client)["mangas"] if item["codigo"] == "INV-DEMO-001")
    assert deleted.status_code == 200
    assert restored["zona"] == "Z-ALMACEN-PIEZAS"


def test_missing_parent_creates_reweigh_pending_but_nonrecoverable_is_blocked(client):
    session_id = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-PIEZAS", "clave": "ses-missing"}
    ).get_json()["id"]
    missing = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas",
        json={"codigo": "INV-DEMO-FALTANTE"},
    )
    blocked = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas",
        json={"codigo": "INV-DEMO-NO-RECUPERABLE"},
    )
    state = inventory_state(client)

    assert missing.status_code == 201
    assert "repesaje" in missing.get_json()["mensaje"].lower()
    assert blocked.status_code == 409
    assert any(item["codigo"] == "INV-DEMO-FALTANTE" for item in state["pendientes"])


def test_deleting_reappearance_restores_baja_and_removes_reweigh_pending(client):
    session_id = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-PIEZAS", "clave": "ses-undo-reappearance"}
    ).get_json()["id"]
    read = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas",
        json={"codigo": "INV-DEMO-FALTANTE"},
    )
    deleted = client.delete(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas/INV-DEMO-FALTANTE"
    )
    state = inventory_state(client)
    manga = next(item for item in state["mangas"] if item["codigo"] == "INV-DEMO-FALTANTE")

    assert read.status_code == 201
    assert deleted.status_code == 200
    assert manga["estado"] == "BAJA_COMPROBADA"
    assert all(item["codigo"] != "INV-DEMO-FALTANTE" for item in state["pendientes"])


def test_prelabel_and_ancient_unit_are_idempotent_and_label_data_is_printable(client):
    prelabel = client.post("/api/mesa/inventario/preetiquetas", json={"clave": "pre-001"})
    replay_prelabel = client.post("/api/mesa/inventario/preetiquetas", json={"clave": "pre-001"})
    code = prelabel.get_json()["codigo"]
    ancient_payload = {
        "codigo": code, "articulo": "ART-TAPA-AZUL", "zona": "Z-ALMACEN-PIEZAS", "clave": "old-001",
    }
    ancient = client.post("/api/mesa/inventario/antiguas", json=ancient_payload)
    replay_ancient = client.post("/api/mesa/inventario/antiguas", json=ancient_payload)
    created_in_mesa = client.post(
        "/api/mesa/inventario/antiguas",
        json={"codigo": "", "articulo": "ART-ASA-BLANCA", "zona": "Z-ALMACEN-PIEZAS", "clave": "old-002"},
    )
    replay_created_in_mesa = client.post(
        "/api/mesa/inventario/antiguas",
        json={"codigo": "", "articulo": "ART-ASA-BLANCA", "zona": "Z-ALMACEN-PIEZAS", "clave": "old-002"},
    )
    state = inventory_state(client)
    label = label_data(code, db_path=client.application.config["MESA_DB_PATH"])

    assert prelabel.status_code == 201
    assert replay_prelabel.status_code == 200
    assert replay_prelabel.get_json() == prelabel.get_json()
    assert code.startswith("INV-")
    assert ancient.status_code == 201
    assert replay_ancient.status_code == 200
    assert replay_ancient.get_json() == ancient.get_json()
    assert created_in_mesa.status_code == 201
    assert replay_created_in_mesa.status_code == 200
    assert replay_created_in_mesa.get_json() == created_in_mesa.get_json()
    assert created_in_mesa.get_json()["codigo"].startswith("INV-MESA-")
    # Ambas fichas se identificaron físicamente en la mesa, aun sin sesión del C66.
    assert {row["codigo"] for row in state["pendientes"]} >= {code, created_in_mesa.get_json()["codigo"]}
    assert code not in state["preetiquetas"]
    assert label["codigo"] == code
    assert label["estado"] == "PENDIENTE_PESAJE"
    assert label["bruto"] is None and label["tara"] is None and label["neto"] is None


def test_removing_c66_reading_preserves_pending_created_in_mesa(client):
    created = client.post(
        "/api/mesa/inventario/antiguas",
        json={"codigo": "", "articulo": "ART-ASA-BLANCA", "zona": "Z-ALMACEN-PIEZAS", "clave": "old-delete-pending"},
    )
    code = created.get_json()["codigo"]
    session_id = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-ARMADO-3P", "clave": "c66-accidental-read"}
    ).get_json()["id"]
    read = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas",
        json={"codigo": code, "confirmar_zona": True, "zona_anterior": "Z-ALMACEN-PIEZAS"},
    )
    deleted = client.delete(f"/api/mesa/inventario/sesiones/{session_id}/lecturas/{code}")
    state = inventory_state(client)
    manga = next(item for item in state["mangas"] if item["codigo"] == code)

    assert created.status_code == 201
    assert read.status_code == 201
    assert deleted.status_code == 200
    assert manga["estado"] == "PENDIENTE_PESAJE"
    assert manga["zona"] == "Z-ALMACEN-PIEZAS"
    pending = next(item for item in state["pendientes"] if item["codigo"] == code)
    assert pending["estado"] == "PENDIENTE_PESAJE"
    assert pending["zona"] == "Z-ALMACEN-PIEZAS"


def test_same_key_with_different_payload_is_rejected(client):
    first = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-PIEZAS", "clave": "same-key"}
    )
    different = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-ARMADO-3P", "clave": "same-key"}
    )

    assert first.status_code == 201
    assert different.status_code == 409
    assert "contenido diferente" in different.get_json()["error"]


def test_weighing_requires_exact_grams_derives_net_and_replays(client):
    code = client.post("/api/mesa/inventario/preetiquetas", json={"clave": "pre-weigh"}).get_json()["codigo"]
    client.post(
        "/api/mesa/inventario/antiguas",
        json={"codigo": code, "articulo": "ART-TAPA-AZUL", "zona": "Z-ALMACEN-PIEZAS", "clave": "old-weigh"},
    )
    payload = {"codigo": code, "bruto": "1.250", "tara": "0.250", "clave": "weigh-001"}
    weighed = client.post("/api/mesa/inventario/pesajes", json=payload)
    replay = client.post("/api/mesa/inventario/pesajes", json=payload)
    invalid = client.post(
        "/api/mesa/inventario/pesajes",
        json={"codigo": code, "bruto": "1.2345", "tara": "0.250", "clave": "weigh-002"},
    )

    assert weighed.status_code == 201
    assert weighed.get_json() == {"codigo": code, "neto": "1.000"}
    pending = next(item for item in inventory_state(client)["pendientes"] if item["codigo"] == code)
    assert pending["estado"] == "PESADA_PENDIENTE_CONFIRMACION"
    assert pending["neto"] == "1.000"
    assert replay.status_code == 200
    assert replay.get_json() == weighed.get_json()
    assert invalid.status_code == 422


@pytest.mark.parametrize("bruto", ["1", "1.5", "1.25", "1.250"])
def test_weighing_accepts_up_to_three_decimal_grams(client, bruto):
    code = client.post(
        "/api/mesa/inventario/preetiquetas", json={"clave": f"pre-{bruto}"}
    ).get_json()["codigo"]
    client.post(
        "/api/mesa/inventario/antiguas",
        json={"codigo": code, "articulo": "ART-TAPA-AZUL", "zona": "Z-ALMACEN-PIEZAS", "clave": f"old-{bruto}"},
    )
    response = client.post(
        "/api/mesa/inventario/pesajes",
        json={"codigo": code, "bruto": bruto, "tara": "0", "clave": f"weigh-{bruto}"},
    )

    assert response.status_code == 201


def test_revision_faltante_and_confirmation_are_one_movement_each(client):
    reviewed = client.post(
        "/api/mesa/inventario/revision",
        json={"codigo": "INV-DEMO-001", "cobertura": True, "movimientos_revisados": True, "busqueda": True},
    )
    repeated_review = client.post(
        "/api/mesa/inventario/revision",
        json={"codigo": "INV-DEMO-001", "cobertura": True, "movimientos_revisados": True, "busqueda": True},
    )
    token = reviewed.get_json()["token"]
    missing_payload = {
        "codigo": "INV-DEMO-001", "token": token, "motivo": "No aparece en zona", "clave": "miss-001",
    }
    missing = client.post("/api/mesa/inventario/faltantes", json=missing_payload)
    replay_missing = client.post("/api/mesa/inventario/faltantes", json=missing_payload)
    preserved = next(item for item in inventory_state(client)["mangas"] if item["codigo"] == "INV-DEMO-001")
    session_id = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-PIEZAS", "clave": "ses-reappear"}
    ).get_json()["id"]
    found = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas", json={"codigo": "INV-DEMO-001"}
    )
    reweighed = client.post(
        "/api/mesa/inventario/pesajes",
        json={"codigo": "INV-DEMO-001", "bruto": "1.500", "tara": "0.250", "clave": "reweigh-001"},
    )
    confirmed = client.post(
        "/api/mesa/inventario/confirmaciones",
        json={"codigo": "INV-DEMO-001", "motivo": "Encontrada", "clave": "confirm-001"},
    )
    replay_confirmed = client.post(
        "/api/mesa/inventario/confirmaciones",
        json={"codigo": "INV-DEMO-001", "motivo": "Encontrada", "clave": "confirm-001"},
    )
    movements = inventory_state(client)["movimientos"]

    assert reviewed.status_code == 201
    assert reviewed.get_json()["neto"] == "1.500"
    assert repeated_review.status_code == 200
    assert repeated_review.get_json() == reviewed.get_json()
    assert missing.status_code == 201
    assert replay_missing.status_code == 200
    assert replay_missing.get_json() == missing.get_json()
    assert preserved["neto"] == "1.500"
    assert found.status_code == 201
    assert reweighed.status_code == 201
    assert reweighed.get_json()["neto"] == "1.250"
    assert confirmed.status_code == 201
    assert replay_confirmed.status_code == 200
    assert replay_confirmed.get_json() == confirmed.get_json()
    assert [movement["delta"] for movement in movements] == ["-1.500", "1.250"]
    assert movements[1]["vinculo_baja"] == movements[0]["id"]
    assert len(movements) == 2


def test_revision_blocks_incomplete_coverage_and_ambiguous_movement_data(client):
    response = client.post(
        "/api/mesa/inventario/revision",
        json={"codigo": "INV-DEMO-001", "cobertura": False, "movimientos_revisados": True, "busqueda": True},
    )
    ambiguous = client.post(
        "/api/mesa/inventario/revision",
        json={"codigo": "INV-DEMO-001", "cobertura": True, "movimientos_revisados": False, "busqueda": True},
    )

    assert response.status_code == 409
    assert ambiguous.status_code == 409


def test_observed_manga_cannot_start_stale_missing_review(client):
    session_id = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-PIEZAS", "clave": "ses-observed"}
    ).get_json()["id"]
    observed = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas", json={"codigo": "INV-DEMO-001"}
    )
    review = client.post(
        "/api/mesa/inventario/revision",
        json={"codigo": "INV-DEMO-001", "cobertura": True, "movimientos_revisados": True, "busqueda": True},
    )

    assert observed.status_code == 201
    assert review.status_code == 409


def test_reading_after_review_invalidates_missing_token(client):
    review = client.post(
        "/api/mesa/inventario/revision",
        json={"codigo": "INV-DEMO-001", "cobertura": True, "movimientos_revisados": True, "busqueda": True},
    )
    token = review.get_json()["token"]
    session_id = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-PIEZAS", "clave": "ses-token-stale"}
    ).get_json()["id"]
    observed = client.post(
        f"/api/mesa/inventario/sesiones/{session_id}/lecturas", json={"codigo": "INV-DEMO-001"}
    )
    missing = client.post(
        "/api/mesa/inventario/faltantes",
        json={"codigo": "INV-DEMO-001", "token": token, "motivo": "No aparece", "clave": "stale-missing"},
    )

    assert review.status_code == 201
    assert observed.status_code == 201
    assert missing.status_code == 409


def test_return_identity_is_visible_without_creating_inventory_movement(client):
    before = inventory_state(client)
    union = client.post(
        "/api/mesa/unions", json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]}
    )
    code = union.get_json()["code"]
    received = client.post(
        "/api/mesa/receive",
        json={"code": code, "net_kg": "1.250", "request_id": "return-inventory-001"},
    )
    after = inventory_state(client)
    manga = next(item for item in after["mangas"] if item["codigo"] == code)

    assert union.status_code == 201
    assert received.status_code == 201
    assert len(after["movimientos"]) == len(before["movimientos"])
    assert manga["estado"] == "RECIBIDA"
    assert manga["neto"] == "1.250"


def test_received_return_has_no_hallazgo_until_first_read_and_restores_null_on_delete(client):
    union = client.post(
        "/api/mesa/unions", json={"codes": ["OFDEMO-OT101-M001", "OFDEMO-OT101-M002"]}
    )
    code = union.get_json()["code"]
    client.post(
        "/api/mesa/receive",
        json={"code": code, "net_kg": "1.250", "request_id": "return-zone-001"},
    )
    initial = next(item for item in inventory_state(client)["mangas"] if item["codigo"] == code)
    session = client.post(
        "/api/mesa/inventario/sesiones", json={"zona": "Z-ALMACEN-PIEZAS", "clave": "return-zone-session"}
    ).get_json()["id"]
    read = client.post(
        f"/api/mesa/inventario/sesiones/{session}/lecturas", json={"codigo": code}
    )
    deleted = client.delete(f"/api/mesa/inventario/sesiones/{session}/lecturas/{code}")
    observed = next(item for item in inventory_state(client)["mangas"] if item["codigo"] == code)

    assert initial["zona"] is None
    assert initial["zona_hallazgo"] is None
    assert read.status_code == 201
    assert deleted.status_code == 409
    assert observed["zona"] == "Z-ALMACEN-PIEZAS"
