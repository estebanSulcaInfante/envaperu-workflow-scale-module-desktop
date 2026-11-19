from concurrent.futures import ThreadPoolExecutor

from run_mesa_pilot import station_app


def test_old_bag_identified_at_the_scale_can_be_scanned_after_reload(tmp_path):
    app, _ = station_app(tmp_path / "mesa.sqlite3")
    endpoint = "/api/mesa/inventario"
    pc = app.test_client()
    state = pc.get(endpoint + "/estado").json
    code = pc.post(endpoint + "/antiguas", json=dict(articulo=state["articulos"][0]["id"],
                   zona=state["zonas"][0]["id"], clave="alta-en-mesa")).json["codigo"]
    assert pc.get(f"{endpoint}/etiquetas/{code}/identidad.tspl").status_code == 200
    fresh = app.test_client().get(endpoint + "/estado").json
    assert code in [bag["codigo"] for bag in fresh["pendientes"]]
    assert fresh["movimientos"] == state["movimientos"]


def test_three_bags_are_weighed_out_of_order_without_duplicate_credit(tmp_path):
    app, _ = station_app(tmp_path / "mesa.sqlite3")
    endpoint = "/api/mesa/inventario"
    pc = app.test_client()
    c66 = app.test_client()
    state = pc.get(endpoint + "/estado").json
    baseline = state["movimientos"]
    zone = state["zonas"][0]["id"]
    item = state["articulos"][0]["id"]
    session = c66.post(endpoint + "/sesiones", json={"zona": zone, "clave": "sesion"}).json["id"]
    bags = []
    for i in range(3):
        code = pc.post(endpoint + "/preetiquetas", json={"clave": f"etiqueta-{i}"}).json["codigo"]
        assert pc.get(f"{endpoint}/etiquetas/{code}/identidad.tspl").status_code == 200
        assert pc.get(f"{endpoint}/etiquetas/{code}/pesaje.tspl").status_code == 422
        old = dict(sesion=session, codigo=code, articulo=item, zona=zone, clave=f"hallazgo-{i}")
        assert c66.post(endpoint + "/antiguas", json=old).status_code == 201
        bags.append(code)
    assert c66.post(f"{endpoint}/sesiones/{session}/cerrar", json={}).status_code == 200
    snapshot = pc.get(endpoint + "/estado").json
    assert snapshot["movimientos"] == baseline
    assert {p["codigo"] for p in snapshot["pendientes"]} >= set(bags)
    expected = {}
    for i in (2, 0, 1):
        code = bags[i]
        weighing = dict(codigo=code, bruto=str(5 + i), tara="1.25", clave=f"pesaje-{i}")
        measured = pc.post(endpoint + "/pesajes", json=weighing)
        assert measured.status_code in (200, 201), measured.json
        expected[code] = f"{3.75 + i:.3f}"
        assert measured.json["neto"] == expected[code]
        assert expected[code] in pc.get(f"{endpoint}/etiquetas/{code}/pesaje.tspl").text
    assert pc.get(endpoint + "/estado").json["movimientos"] == baseline

    def confirm(i):
        with app.test_client() as station:
            return station.post(endpoint + "/confirmaciones", json=dict(codigo=bags[0],
                                motivo="Alta verificada en mesa", clave=f"confirmar-{i}")).status_code
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(confirm, (1, 2)))
    assert any(status in (200, 201) for status in responses)
    movements = [row for row in pc.get(endpoint + "/estado").json["movimientos"] if row not in baseline]
    assert len(movements) == 1 and movements[0]["codigo"] == bags[0]
    assert float(movements[0]["delta"]) == float(expected[bags[0]])
