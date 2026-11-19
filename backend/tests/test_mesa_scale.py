from mesa_pilot import create_app
from mesa_scale import AccuraReading, parse_accura_line


def test_parser_accepts_observed_stable_net_kg_and_pcs_without_promoting_pcs():
    reading = parse_accura_line(b"ST,NT,+   0.40kg\r\n")
    pcs = parse_accura_line(b"ST,NT,+     46Pcs\r\n")

    assert reading == AccuraReading(stable=True, base="NT", kg="0.40", unit="kg")
    assert pcs == AccuraReading(stable=True, base="NT", kg=None, unit="Pcs")


def test_parser_does_not_produce_capturable_weight_for_unstable_or_non_positive():
    for line in (b"US,NT,+   0.40kg\r\n", b"ST,NT,+   0.00kg\r\n", b"ST,NT,-   0.40kg\r\n"):
        reading = parse_accura_line(line)
        assert reading is not None and reading.kg is None


def test_reader_waits_for_crlf_and_clears_after_incomplete_or_bad_line():
    from mesa_scale import MesaScaleReader

    reader = MesaScaleReader("COM9", serial_factory=lambda **_: None)
    reader.feed_for_test(b"ST,NT,+   0.40kg\r")
    assert reader.status()["kg"] is None
    reader.feed_for_test(b"\n")
    assert reader.status()["kg"] == "0.40"
    reader.feed_for_test(b"garbled\r\n")
    assert reader.status()["kg"] is None


def test_kg_then_pcs_us_or_garbage_blocks_snapshot_without_reviving_old_weight(tmp_path):
    from mesa_scale import MesaScaleReader

    reader = MesaScaleReader("COM9", serial_factory=lambda **_: None)
    app = create_app(tmp_path / "mesa.sqlite3", scale_reader=reader)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        reader.feed_for_test(b"ST,NT,+   0.40kg\r\n")
        assert client.get("/api/mesa/balanza").get_json()["kg"] == "0.40"
        for frame in (
            b"ST,NT,+     46Pcs\r\n",
            b"US,NT,+   0.40kg\r\n",
            b"garbage\r\n",
        ):
            reader.feed_for_test(frame)
            status = client.get("/api/mesa/balanza").get_json()
            assert status["kg"] is None
            assert client.post("/api/mesa/balanza/capturas", json={"codigo": "OFDEMO-OT101-M003"}).status_code == 409


def test_silent_accura_expires_snapshot_and_blocks_new_capture(tmp_path):
    import time
    from mesa_scale import MesaScaleReader

    reader = MesaScaleReader("COM9", serial_factory=lambda **_: None, freshness_seconds=0.01)
    reader.feed_for_test(b"ST,NT,+   0.40kg\r\n")
    time.sleep(0.03)
    app = create_app(tmp_path / "mesa.sqlite3", scale_reader=reader)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        assert client.get("/api/mesa/balanza").get_json()["kg"] is None
        assert client.post("/api/mesa/balanza/capturas", json={"codigo": "OFDEMO-OT101-M003"}).status_code == 409


def test_mesa_scale_endpoint_is_manual_without_port(tmp_path):
    app = create_app(tmp_path / "mesa.sqlite3")
    app.config.update(TESTING=True)

    with app.test_client() as client:
        assert client.get("/api/mesa/balanza").get_json() == {
            "modo": "manual",
            "disponible": True,
            "base": None,
            "kg": None,
            "mensaje": "Modo manual; no hay lector Accura configurado.",
        }


def test_physical_capture_is_fresh_and_bound_to_manga(tmp_path):
    from mesa_scale import MesaScaleReader

    reader = MesaScaleReader("COM9", serial_factory=lambda **_: None)
    reader.feed_for_test(b"ST,NT,+   0.40kg\r\n")
    app = create_app(tmp_path / "mesa.sqlite3", scale_reader=reader)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        status = client.get("/api/mesa/balanza").get_json()
        assert status["modo"] == "accura"
        assert status["kg"] == "0.40"
        capture = client.post("/api/mesa/balanza/capturas", json={"codigo": "OFDEMO-OT101-M003"})
        assert capture.status_code == 201
        token = capture.get_json()["token"]
        received = client.post(
            "/api/mesa/receive",
            json={"code": "OFDEMO-OT101-M003", "scale_token": token, "request_id": "physical-1"},
        )
        assert received.status_code == 201
        mismatch = client.post(
            "/api/mesa/receive",
            json={"code": "OFDEMO-OT101-M004", "scale_token": token, "request_id": "physical-2"},
        )
        assert mismatch.status_code == 409


def test_gs_is_not_invented_as_net_for_return(tmp_path):
    from mesa_scale import MesaScaleReader

    reader = MesaScaleReader("COM9", serial_factory=lambda **_: None)
    reader.feed_for_test(b"ST,GS,+   0.40kg\r\n")
    app = create_app(tmp_path / "mesa.sqlite3", scale_reader=reader)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        capture = client.post("/api/mesa/balanza/capturas", json={"codigo": "OFDEMO-OT101-M003"})
        token = capture.get_json()["token"]
        rejected = client.post("/api/mesa/receive", json={
            "code": "OFDEMO-OT101-M003", "scale_token": token, "request_id": "gs-return",
        })
        assert rejected.status_code == 409
        assert "base NT" in rejected.get_json()["error"]


def test_physical_return_replay_requires_original_token_and_rejects_substitution(tmp_path):
    from mesa_scale import MesaScaleReader

    reader = MesaScaleReader("COM9", serial_factory=lambda **_: None)
    reader.feed_for_test(b"ST,NT,+   0.40kg\r\n")
    app = create_app(tmp_path / "mesa.sqlite3", scale_reader=reader)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        first_capture = client.post("/api/mesa/balanza/capturas", json={"codigo": "OFDEMO-OT101-M003"}).get_json()
        first = client.post("/api/mesa/receive", json={
            "code": "OFDEMO-OT101-M003", "scale_token": first_capture["token"], "request_id": "physical-replay",
        })
        replay = client.post("/api/mesa/receive", json={
            "code": "OFDEMO-OT101-M003", "scale_token": first_capture["token"], "request_id": "physical-replay",
        })
        reader.feed_for_test(b"ST,NT,+   0.50kg\r\n")
        replacement = client.post("/api/mesa/balanza/capturas", json={"codigo": "OFDEMO-OT101-M003"})
        substituted = client.post("/api/mesa/receive", json={
            "code": "OFDEMO-OT101-M003", "scale_token": replacement.get_json()["token"],
            "request_id": "physical-replay",
        })
        assert first.status_code == 201
        assert replay.status_code == 200
        assert substituted.status_code == 409


def test_physical_inventory_requires_explicit_zero_tare_confirmation(tmp_path):
    from mesa_scale import MesaScaleReader

    reader = MesaScaleReader("COM9", serial_factory=lambda **_: None)
    reader.feed_for_test(b"ST,NT,+   0.40kg\r\n")
    app = create_app(tmp_path / "mesa.sqlite3", scale_reader=reader)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        code = client.post("/api/mesa/inventario/preetiquetas", json={"clave": "pre-scale"}).get_json()["codigo"]
        client.post("/api/mesa/inventario/antiguas", json={
            "codigo": code, "articulo": "ART-TAPA-AZUL", "zona": "Z-ALMACEN-PIEZAS", "clave": "old-scale",
        })
        token = client.post("/api/mesa/balanza/capturas", json={"codigo": code}).get_json()["token"]
        blocked = client.post("/api/mesa/inventario/pesajes", json={
            "codigo": code, "scale_token": token, "bruto": "0.400", "tara": "0", "clave": "weigh-scale",
        })
        assert blocked.status_code == 409
        accepted = client.post("/api/mesa/inventario/pesajes", json={
            "codigo": code, "scale_token": token, "bruto": "0.400", "tara": "0", "confirmar_tara_cero": True,
            "clave": "weigh-scale-confirmed",
        })
        assert accepted.status_code == 201


def test_physical_inventory_subtracts_operator_tare_once(tmp_path):
    from mesa_scale import MesaScaleReader

    reader = MesaScaleReader("COM9", serial_factory=lambda **_: None)
    reader.feed_for_test(b"ST,NT,+   0.40kg\r\n")
    app = create_app(tmp_path / "mesa.sqlite3", scale_reader=reader)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        code = client.post("/api/mesa/inventario/preetiquetas", json={"clave": "pre-tare"}).get_json()["codigo"]
        client.post("/api/mesa/inventario/antiguas", json={
            "codigo": code, "articulo": "ART-TAPA-AZUL", "zona": "Z-ALMACEN-PIEZAS", "clave": "old-tare",
        })
        token = client.post("/api/mesa/balanza/capturas", json={"codigo": code}).get_json()["token"]
        measured = client.post("/api/mesa/inventario/pesajes", json={
            "codigo": code, "scale_token": token, "bruto": "0.400", "tara": "0.100", "clave": "weigh-tare",
        })
        assert measured.status_code == 409
        assert "no fue tarado" in measured.get_json()["error"]
        accepted = client.post("/api/mesa/inventario/pesajes", json={
            "codigo": code, "scale_token": token, "bruto": "0.400", "tara": "0.100",
            "confirmar_sin_tara_indicador": True, "clave": "weigh-tare-confirmed",
        })
        assert accepted.status_code == 201
        assert accepted.get_json()["neto"] == "0.300"


def test_reader_reconnects_after_serial_failure_and_reads_again():
    import time
    from mesa_scale import MesaScaleReader

    class FakeSerial:
        def __init__(self, frames, fail=False):
            self.frames = list(frames)
            self.fail = fail
            self.closed = False
            self.dtr = True
            self.rts = True

        def readline(self):
            if self.fail:
                self.fail = False
                raise OSError("cable removed")
            if self.frames:
                return self.frames.pop(0)
            time.sleep(0.01)
            return b""

        def close(self):
            self.closed = True

    opened = []

    def factory(**kwargs):
        opened.append(kwargs)
        if len(opened) == 1:
            return FakeSerial([], fail=True)
        return FakeSerial([b"ST,NT,+   0.40kg\r\n"])

    reader = MesaScaleReader("COM9", serial_factory=factory)
    assert reader.start() is True
    deadline = time.time() + 3
    while time.time() < deadline and reader.status()["kg"] != "0.40":
        time.sleep(0.02)
    assert reader.status()["disponible"] is True
    assert reader.status()["kg"] == "0.40"
    assert opened[0]["baudrate"] == 9600
    assert opened[0]["bytesize"] == 8 and opened[0]["parity"] == "N" and opened[0]["stopbits"] == 1
    assert opened[0]["rtscts"] is False and opened[0]["dsrdtr"] is False
    reader.close()


def test_reader_retries_when_initial_open_fails_without_pulsing_lines():
    import time
    from mesa_scale import MesaScaleReader

    opened = []

    class LateSerial:
        def __init__(self, *, fail_open):
            self.fail_open = fail_open
            self.is_open = False
            self.port = None
            self.dtr = True
            self.rts = True
            self.events = []

        def open(self):
            self.events.append((self.port, self.dtr, self.rts))
            if self.fail_open:
                raise OSError("COM not present yet")
            self.is_open = True

        def readline(self):
            if self.is_open:
                self.is_open = "emitted"
                return b"ST,NT,+   0.40kg\r\n"
            time.sleep(0.01)
            return b""

        def close(self):
            self.is_open = False

    def factory(**kwargs):
        opened.append((kwargs, LateSerial(fail_open=len(opened) == 0)))
        return opened[-1][1]

    reader = MesaScaleReader("COM9", serial_factory=factory)
    assert reader.start() is False
    deadline = time.time() + 3
    while time.time() < deadline and reader.status()["kg"] != "0.40":
        time.sleep(0.02)
    assert reader.status()["kg"] == "0.40"
    assert opened[0][0]["port"] is None
    assert opened[0][1].events[0] == ("COM9", False, False)
    reader.close()


def test_reader_close_interrupts_late_reconnect_retry():
    import time
    from mesa_scale import MesaScaleReader

    attempts = []

    class MissingSerial:
        is_open = False
        port = None
        dtr = True
        rts = True

        def open(self):
            raise OSError("still absent")

        def close(self):
            pass

    def factory(**kwargs):
        attempts.append(kwargs)
        return MissingSerial()

    reader = MesaScaleReader("COM9", serial_factory=factory)
    assert reader.start() is False
    time.sleep(0.05)
    reader.close()
    assert reader.status()["disponible"] is False
    assert reader._thread is None
