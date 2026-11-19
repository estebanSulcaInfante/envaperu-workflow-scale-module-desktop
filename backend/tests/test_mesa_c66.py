import re

from flask import Flask
from werkzeug.test import Client

from mesa_c66 import ReaderAccess


def test_reader_is_paired_once_and_only_posts_scans_from_its_own_origin():
    app = Flask(__name__)
    app.add_url_rule("/api/mesa/inventario/sesiones/S1/lecturas", "read", lambda: {"ok": True}, methods=["POST"])
    app.add_url_rule("/api/mesa/inventario/confirmaciones", "adjust", lambda: {"ok": True}, methods=["POST"])
    access = ReaderAccess(app, "192.168.1.37:5198")
    client = Client(access)
    origin = "http://192.168.1.37:5198"
    opts = {"base_url": origin}
    reads = "/api/mesa/inventario/sesiones/S1/lecturas"
    assert client.get("/inventario/c66", **opts).status_code == 403
    with app.test_request_context():
        pairing = access.pairing_page().get_data(as_text=True)
    link = re.search(r'href="http://[^"]+(/vincular/[\w-]+)"', pairing)[1]
    assert client.get(link, **opts).status_code == 303
    assert client.get(link, **opts).status_code == 403
    assert client.post(reads, headers={"Origin": origin}, **opts).json == {"ok": True}
    assert client.post(reads, headers={"Origin": "http://otro"}, **opts).status_code == 403
    assert client.post("/api/mesa/inventario/confirmaciones", headers={"Origin": origin}, **opts).status_code == 403
    assert client.post(
        "/api/mesa/inventario/antiguas",
        headers={"Origin": origin},
        json={"codigo": "INV-001", "sesion": "S1"},
        **opts,
    ).status_code == 403
    assert client.get("/inventario/conectar", **opts).status_code == 403
