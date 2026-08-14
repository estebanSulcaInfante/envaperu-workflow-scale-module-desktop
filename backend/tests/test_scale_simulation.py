from app import create_app, db
from app.services.printer_service import PrinterService


def _application(tmp_path, *, enabled):
    database = tmp_path / ("enabled.db" if enabled else "disabled.db")
    return create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "ALLOW_SCALE_SIMULATION": enabled,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
        },
        start_workers=False,
    )


def test_local_station_can_inject_stable_simulated_weight(tmp_path):
    app = _application(tmp_path, enabled=True)
    try:
        client = app.test_client()
        status = client.get("/api/balanza/status").get_json()
        assert status["simulation_enabled"] is True

        response = client.post(
            "/api/balanza/simular-peso",
            json={"peso_kg": 12.3456},
        )
        assert response.status_code == 200
        assert response.get_json() == {
            "status": "ok",
            "peso_kg": 12.346,
            "stable": True,
            "simulated": True,
        }
        assert client.get("/api/balanza/ultimo-peso").get_json()["stable"] is True
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_simulation_is_fail_closed_when_disabled(tmp_path):
    app = _application(tmp_path, enabled=False)
    try:
        client = app.test_client()
        response = client.post(
            "/api/balanza/simular-peso",
            json={"peso_kg": 10},
        )
        assert response.status_code == 403
        assert response.get_json()["code"] == "SCALE_SIMULATION_DISABLED"
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_simulated_printer_never_opens_windows_spooler(tmp_path, monkeypatch):
    app = _application(tmp_path, enabled=True)
    app.config["SIMULATE_PRINTER"] = True
    printer = PrinterService(printer_type="TSPL", printer_name="REAL-PRINTER")
    monkeypatch.setattr(
        printer,
        "connect",
        lambda: (_ for _ in ()).throw(AssertionError("spooler must not open")),
    )
    try:
        with app.app_context():
            assert printer.print_tspl("SIZE 109 mm,50 mm") is True
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
