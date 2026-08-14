from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from app import create_app, db
from app.models.scm_label_print_attempt import ScmLabelPrintAttempt
from app.services.scm_prelabel_service import ScmPrelabelService


def _label(code):
    manga_id = str(uuid4())
    label_id = str(uuid4())
    payload = {
        "codigo_manga": code,
        "op_ot": "OP0084 - OT-000001",
        "fecha_ot": "2026-07-28",
        "maquinista": "Juan Perez",
        "pieza_color": "Asa fucsia (PC-000001)",
        "color": "FUCSIA SOLIDO",
        "tipo_manga": "Manga estandar",
        "cantidad_planificada_un": "100",
        "qr": {
            "v": 1,
            "type": "SCM_MANGA_LABEL",
            "manga_id": manga_id,
            "label_id": label_id,
            "label_type": "PREPESAJE",
            "label_version": 1,
        },
    }
    return {
        "public_id": label_id,
        "payload_hash": "a" * 64,
        "payload": payload,
    }


def _canonical_label(code):
    label = _label(code)
    label["payload"].pop("op_ot")
    label["payload"]["of_ot"] = "OF-000900 - OT-000001"
    return label


def _color_work_label(code):
    label = _canonical_label(code)
    work_id = str(uuid4())
    label["payload"]["template"] = {"version": "PREPESAJE_TSPL_3"}
    label["payload"]["trabajo_color"] = {
        "id": work_id,
        "codigo": "OT-000001-TC01",
        "corrida_fabricacion_id": str(uuid4()),
    }
    label["payload"]["qr"]["trabajo_color_id"] = work_id
    return label


def _assembly_label(code):
    label = _label(code)
    label["payload"].pop("op_ot")
    label["payload"]["oa_ot"] = "OA-000321 - OT-000777"
    return label


def test_lote_impar_deja_segunda_columna_vacia():
    tspl = ScmPrelabelService().generate_tspl(
        {"labels": [_label("OP0084-OT001-M001")]},
        printed_at=datetime(2026, 7, 28, 12, 30, tzinfo=timezone.utc),
    )

    assert "SIZE 109 mm, 50 mm" in tspl
    assert "GAP 3 mm, 0 mm" in tspl
    assert "OP0084-OT001-M001" in tspl
    assert "IMP.: 28/07/2026 07:30" in tspl
    assert "QRCODE 144" in tspl
    assert ",L,4,A,0," in tspl
    assert "TEXT 469" not in tspl


def test_plantilla_v2_renderiza_of_ot_y_conserva_qr_v1():
    label = _canonical_label("OF000900-OT001-M001")
    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})
    svg = ScmPrelabelService().generate_preview_svg({"labels": [label]})

    assert "OF/OT: OF-000900 - OT-000001" in tspl
    assert "OP/OT:" not in tspl
    assert label["payload"]["qr"]["label_id"] in tspl
    assert "OF/OT: OF-000900 - OT-000001" in svg


def test_trabajo_color_conserva_rotulo_simple_y_contexto_en_qr():
    label = _color_work_label("OF000900-OT001-M001")
    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})
    svg = ScmPrelabelService().generate_preview_svg({"labels": [label]})

    assert "OF/OT: OF-000900 - OT-000001" in tspl
    assert "TC01" not in tspl
    assert label["payload"]["trabajo_color"]["id"] in tspl
    assert "OF/OT: OF-000900 - OT-000001" in svg


def test_armado_renderiza_oa_ot_sin_perder_la_identidad():
    label = _assembly_label("OA000321-OT777-M001")
    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})
    svg = ScmPrelabelService().generate_preview_svg({"labels": [label]})

    assert "OA/OT: OA-000321 - OT-000777" in tspl
    assert "OF/OT:" not in tspl
    assert "OP/OT:" not in tspl
    assert "OA/OT: OA-000321 - OT-000777" in svg


def test_dos_columnas_contienen_identidades_distintas():
    left = _label("OP0084-OT001-M001")
    right = deepcopy(_label("OP0084-OT001-M002"))
    tspl = ScmPrelabelService().generate_tspl({
        "labels": [left, right]
    })

    assert tspl.count("QRCODE") == 2
    assert "OP0084-OT001-M001" in tspl
    assert "OP0084-OT001-M002" in tspl
    assert left["payload"]["qr"]["label_id"] in tspl
    assert right["payload"]["qr"]["label_id"] in tspl


def test_preview_web_respeta_hoja_fisica_y_genera_qr():
    svg = ScmPrelabelService().generate_preview_svg(
        {"labels": [_label("OP0084-OT001-M001")]},
        printed_at=datetime(2026, 7, 28, 12, 30, tzinfo=timezone.utc),
    )

    assert 'viewBox="0 0 872 400"' in svg
    assert 'width="109mm" height="50mm"' in svg
    assert "OP0084-OT001-M001" in svg
    assert "data:image/png;base64," in svg
    assert 'width="120" height="120"' in svg
    assert "COLUMNA LIBRE" in svg


def test_bandeja_y_preview_consultan_central_sin_reclamar():
    job = {
        "print_job_id": str(uuid4()),
        "status": "PENDING",
        "estado": "GENERADO",
        "created_at": "2026-08-09T15:00:00+00:00",
        "processed_at": None,
        "plantilla_version": "PREPESAJE_TSPL_3",
        "labels": [_label("OF000900-OT001-M001")],
    }

    class Central:
        def __init__(self):
            self.claims = []

        def list_scm_print_jobs(self, station_id, *, status, limit):
            assert station_id == "PESAJE-INBOX-01"
            assert status == "PENDING"
            assert limit == 20
            return {"print_jobs": [job], "count": 1}

        def get_scm_print_job(self, station_id, print_job_id):
            assert station_id == "PESAJE-INBOX-01"
            assert print_job_id == job["print_job_id"]
            return job

        def claim_scm_print_job(self, station_id, print_job_id):
            self.claims.append((station_id, print_job_id))
            return job

    central = Central()
    service = ScmPrelabelService(client=central)
    service._station_id = staticmethod(lambda: "PESAJE-INBOX-01")

    assert service.list_jobs(status="PENDING", limit=20) == {
        "print_jobs": [job],
        "count": 1,
    }
    assert service.fetch(job["print_job_id"]) == job
    assert central.claims == []


def test_endpoint_local_expone_bandeja_y_preview_sin_efectos(tmp_path):
    job_id = str(uuid4())
    job = {
        "print_job_id": job_id,
        "status": "PENDING",
        "estado": "GENERADO",
        "created_at": "2026-08-09T15:00:00+00:00",
        "processed_at": None,
        "plantilla_version": "PREPESAJE_TSPL_3",
        "labels": [_label("OF000900-OT001-M001")],
    }

    class Service:
        def __init__(self):
            self.print_calls = 0

        def list_jobs(self, *, status, limit):
            assert (status, limit) == ("PENDING", 20)
            return {"print_jobs": [job], "count": 1}

        def fetch(self, requested_id):
            assert requested_id == job_id
            return job

        def generate_tspl(self, requested_job):
            assert requested_job is job
            return "SIZE 109 mm, 50 mm"

        def generate_preview_svg(self, requested_job):
            assert requested_job is job
            return "<svg/>"

    database = tmp_path / "pesajes.db"
    service = Service()
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "SCM_PRELABEL_SERVICE": service,
        },
        start_workers=False,
    )
    try:
        client = app.test_client()
        inbox = client.get(
            "/api/local/v1/scm/print-jobs?status=PENDING&limit=20"
        )
        preview = client.get(f"/api/local/v1/scm/print-jobs/{job_id}")

        assert inbox.status_code == 200
        assert inbox.get_json() == {"print_jobs": [job], "count": 1}
        assert preview.status_code == 200
        assert preview.get_json() == {
            "print_job": job,
            "tspl": "SIZE 109 mm, 50 mm",
            "preview_svg": "<svg/>",
        }
        assert service.print_calls == 0
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_fallo_sin_emision_se_puede_reintentar_sin_borrar_evidencia(tmp_path):
    labels = [_label("OP0084-OT001-M001"), _label("OP0084-OT001-M002")]
    job = {
        "print_job_id": str(uuid4()),
        "labels": labels,
    }

    class Central:
        def claim_scm_print_job(self, _station_id, _job_id):
            return job

        def acknowledge_scm_print_job(
            self, _station_id, _job_id, payload
        ):
            return {"results": payload["results"]}

    class Printer:
        printer_name = "TSC"

        def __init__(self):
            self.results = iter((False, True))

        def print_tspl(self, _payload):
            return next(self.results)

    database = tmp_path / "pesajes.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_ID": "PESAJE-RETRY-01",
        },
        start_workers=False,
    )
    try:
        with app.app_context():
            service = ScmPrelabelService(
                client=Central(),
                printer=Printer(),
            )
            assert service.print_job(job["print_job_id"])["result"] == (
                "FALLIDA_SIN_EMISION"
            )
            assert service.print_job(job["print_job_id"])["result"] == "IMPRESA"
            attempts = ScmLabelPrintAttempt.query.order_by(
                ScmLabelPrintAttempt.id
            ).all()
            assert len(attempts) == 4
            assert [attempt.result for attempt in attempts] == [
                "FALLIDA_SIN_EMISION",
                "FALLIDA_SIN_EMISION",
                "IMPRESA",
                "IMPRESA",
            ]
            assert all(
                len(attempt.rendered_payload_hash) == 64
                for attempt in attempts
            )
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
