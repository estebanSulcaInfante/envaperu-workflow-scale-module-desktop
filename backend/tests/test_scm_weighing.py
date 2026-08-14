from uuid import uuid4

import pytest

from app import create_app, db
from app.models.pesaje import Pesaje
from app.services.scm_weighing_service import (
    ScmWeighingLocalError,
    ScmWeighingService,
    parse_scm_label_id,
)


def _post_label(label_id, manga_id):
    payload = {
        "codigo_manga": "OP0084-OT001-M001",
        "op_ot": "OP0084 - OT-000001",
        "fecha_ot": "2026-07-28",
        "maquinista": "Juan Perez",
        "pieza_color": "Asa fucsia (PC-000001)",
        "color": "FUCSIA SOLIDO",
        "tipo_manga": "NORMAL",
        "cantidad_planificada_un": "100",
        "kg_fisico": "10.000",
        "kg_produccion_ot": "10.000",
        "qr": {
            "v": 1,
            "type": "SCM_MANGA_LABEL",
            "manga_id": manga_id,
            "label_id": label_id,
            "label_type": "POSTPESAJE",
            "label_version": 1,
        },
    }
    return {
        "public_id": label_id,
        "payload_hash": "d" * 64,
        "payload": payload,
    }


def test_qr_legacy_no_entra_al_flujo_scm():
    with pytest.raises(ScmWeighingLocalError) as error:
        parse_scm_label_id("1;MOLDE;MAQUINA;OP0084")
    assert error.value.code == "LEGACY_QR_NOT_ACCEPTED"


def test_qr_demo_local_resuelve_sin_consultar_central(tmp_path):
    database = tmp_path / "demo.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "ALLOW_LOCAL_SCM_DEMO": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
        },
        start_workers=False,
    )
    try:
        client = app.test_client()
        response = client.post(
            "/api/local/v1/scm/weighing/resolve",
            json={"qr": '{"v":1,"type":"SCM_MANGA_LABEL","label_id":"00000000-0000-4000-8000-000000000101"}'},
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["demo_only"] is True
        assert payload["manga"]["codigo"] == "MNG-LOCAL-DEMO-001"
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_f2_confirma_central_antes_de_imprimir_y_no_crea_pesaje_local(
    tmp_path,
):
    prelabel_id = str(uuid4())
    postlabel_id = str(uuid4())
    manga_id = str(uuid4())
    print_job_id = str(uuid4())
    calls = []

    class Central:
        def resolve_scm_manga_label(self, label_id):
            calls.append(("resolve", label_id))
            return {
                "can_weigh": True,
                "manga": {"tara_nominal_kg": "0.100"},
            }

        def confirm_scm_manga_weighing(self, operation_id, payload):
            calls.append(("confirm", operation_id, payload))
            return {
                "print_job_id": print_job_id,
                "post_label": {"public_id": postlabel_id},
                "weighing": {"peso_fisico_neto_kg": "10.000"},
            }

        def get_scm_print_job(self, _station_id, job_id):
            calls.append(("fetch_print", job_id))
            return {
                "print_job_id": print_job_id,
                "plantilla_version": "POSTPESAJE_TSPL_1",
                "labels": [_post_label(postlabel_id, manga_id)],
            }

        def claim_scm_print_job(self, station_id, job_id):
            return self.get_scm_print_job(station_id, job_id)

        def acknowledge_scm_print_job(
            self, _station_id, job_id, payload
        ):
            calls.append(("ack_print", job_id, payload))
            return {"estado": "PROCESADO"}

    class Printer:
        printer_name = "TSC"

        def print_tspl(self, tspl):
            calls.append(("print", tspl))
            return True

    database = tmp_path / "station.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_ID": "PESAJE-D-01",
            "SCM_OPERATOR_ID": "7",
        },
        start_workers=False,
    )
    try:
        with app.app_context():
            service = ScmWeighingService(
                client=Central(),
                printer=Printer(),
                scale_snapshot=lambda: {
                    "peso_kg": 10.1,
                    "stable": True,
                },
            )
            result = service.confirm(
                operation_id=str(uuid4()),
                label_id=prelabel_id,
            )

            assert result["print_result"]["result"] == "IMPRESA"
            assert [item[0] for item in calls] == [
                "resolve",
                "confirm",
                "fetch_print",
                "print",
                "ack_print",
            ]
            confirm_payload = calls[1][2]
            assert confirm_payload["peso_bruto_kg"] == "10.100"
            assert confirm_payload["tara_kg"] == "0.100"
            assert confirm_payload["pesado_por_id"] == 7
            assert "QRCODE 144" in calls[3][1]
            assert "KG FIS.: 10.000" in calls[3][1]
            assert Pesaje.query.count() == 0
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
