from datetime import datetime, timezone
import sqlite3

from mesa_central import CentralError, bind_central
from mesa_pilot import create_app
from mesa_scale import MesaScaleReader


class Central:
    def __init__(self):
        self.calls = []

    def call(self, method, path, data=None, key=None):
        self.calls.append((method, path, data, key))
        if path == "/receive" and len(self.calls) == 1:
            raise CentralError("Respuesta perdida", 503)
        return {"aceptado": True}, 200


def test_retry_preserves_attested_reading_even_after_expiry(tmp_path):
    db = tmp_path / "dispositivo.sqlite3"
    station = Central()
    reader = MesaScaleReader("TEST")
    app = create_app(db, scale_reader=reader, central=station)
    bind_central(app, station)
    client = app.test_client()
    reader.feed_for_test(b"ST,NT,+   1.50kg\r\n")
    capture = client.post("/api/mesa/balanza/capturas", json={"codigo": "REAL-1"}).json
    payload = dict(code="REAL-1", net_kg="1.500", scale_token=capture["token"], request_id="same")
    assert client.post("/api/mesa/receive", json=payload).status_code == 503
    with sqlite3.connect(db) as conn:
        conn.execute("update mesa_scale_captures set expires_at='2000-01-01T00:00:00Z'")
    assert client.post("/api/mesa/receive", json=payload).status_code == 200
    assert station.calls[0] == station.calls[1]
    assert station.calls[1][2]["captura"]["kg"] == "1.50"
    assert client.post("/api/mesa/receive", json=dict(payload, net_kg="8")).status_code == 409
    assert client.post("/api/mesa/receive", json=dict(payload, captura={})).status_code == 422
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from receipts").fetchone()[0] == 0
        assert conn.execute("select count(*) from units").fetchone()[0] == 0


def test_no_capture_or_spoofed_origin_never_reaches_central(tmp_path):
    central = Central()
    app = create_app(tmp_path / "edge.db", scale_reader=MesaScaleReader(None, configured=False), central=central)
    bind_central(app, central)
    client = app.test_client()
    assert client.post("/api/mesa/receive", json={"code":"A", "net_kg":"1", "request_id":"123"}).status_code == 409
    assert client.post("/api/mesa/unions", headers={"Origin":"https://otro.example"}, json={"codes":["A","B"]}).status_code == 403
    assert not central.calls


def test_station_review_bookmark_opens_scm_without_device_credentials(tmp_path):
    from run_mesa_pilot import station_app

    app, _ = station_app(tmp_path / "mesa.sqlite", scale_unconfigured=True, central=Central())
    response = app.test_client().get("/inventario/revision")
    assert response.status_code == 302
    assert response.location == "https://envaperu-scm-dashboard.onrender.com/almacen/revision-faltantes"
