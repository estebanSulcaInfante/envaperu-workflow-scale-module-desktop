import uuid

from app import create_app, db
from app.services.portfolio_demo_service import (
    DEMO_PRELABEL_ID,
    DEMO_PREPRINT_JOB_ID,
    PortfolioDemoPrelabelService,
    PortfolioDemoWeighingService,
    demo_qr_text,
)


def _application(tmp_path):
    database = tmp_path / "edge-demo.db"
    return create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "PORTFOLIO_DEMO_MODE": True,
            "ALLOW_SCALE_SIMULATION": True,
            "SIMULATE_PRINTER": True,
            "STATION_ID": "PESAJE-PORTFOLIO-DEMO",
            "STATION_UUID": "00000000-0000-4000-8000-000000000501",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "SCM_PRELABEL_SERVICE": PortfolioDemoPrelabelService(),
            "SCM_WEIGHING_SERVICE": PortfolioDemoWeighingService(),
        },
        start_workers=False,
    )


def test_public_edge_demo_exposes_only_simulated_hardware(tmp_path):
    app = _application(tmp_path)
    try:
        client = app.test_client()

        scale = client.get("/api/balanza/status").get_json()
        ready = client.get("/api/local/v1/health/ready").get_json()

        assert scale == {
            "port": "SIMULADA",
            "baud_rate": None,
            "connected": True,
            "listening": True,
            "simulation_enabled": True,
            "portfolio_demo": True,
        }
        assert ready["central"] == {
            "state": "PORTFOLIO_DEMO",
            "last_central_ack_utc": None,
            "last_error_code": None,
            "isolated": True,
        }
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_public_edge_demo_runs_qr_weight_and_label_flow(tmp_path):
    app = _application(tmp_path)
    try:
        client = app.test_client()

        inbox = client.get("/api/local/v1/scm/print-jobs").get_json()
        assert inbox["count"] == 1
        assert inbox["print_jobs"][0]["print_job_id"] == DEMO_PREPRINT_JOB_ID

        preview = client.get(
            f"/api/local/v1/scm/print-jobs/{DEMO_PREPRINT_JOB_ID}"
        ).get_json()
        assert "viewBox=\"0 0 872 400\"" in preview["preview_svg"]

        weight = client.post(
            "/api/balanza/simular-peso", json={"peso_kg": 8.475}
        )
        assert weight.status_code == 200

        resolved = client.post(
            "/api/local/v1/scm/weighing/resolve",
            json={"qr": demo_qr_text()},
        ).get_json()
        assert resolved["portfolio_demo"] is True
        assert resolved["scanned_label_id"] == DEMO_PRELABEL_ID

        operation_id = str(uuid.uuid4())
        first = client.post(
            "/api/local/v1/scm/weighing/confirm",
            headers={"Idempotency-Key": operation_id},
            json={"label_id": DEMO_PRELABEL_ID},
        )
        second = client.post(
            "/api/local/v1/scm/weighing/confirm",
            headers={"Idempotency-Key": operation_id},
            json={"label_id": DEMO_PRELABEL_ID},
        )

        assert first.status_code == 200
        assert first.get_json() == second.get_json()
        result = first.get_json()
        assert result["confirmed"]["weighing"]["peso_fisico_neto_kg"] == "8.375"
        assert result["print_result"]["result"] == "IMPRESA"
        assert result["print_result"]["simulated"] is True
        assert "KG FIS.: 8.375" in result["print_result"]["preview_svg"]
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
