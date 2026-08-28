from copy import deepcopy
from datetime import datetime, timezone
import json
import re
from uuid import uuid4

import pytest
import qrcode
from qrcode.constants import ERROR_CORRECT_L

from app import create_app, db
from app.models.scm_label_print_attempt import ScmLabelPrintAttempt
from app.services.central_api_client import CentralApiError
from app.services.printer_service import PrinterEmissionResult
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


def _post_weighing_label(code):
    label = _color_work_label(code)
    label["payload"]["qr"]["label_type"] = "POSTPESAJE"
    label["payload"]["cantidad_confirmada_un"] = "100"
    label["payload"]["kg_fisico"] = "8.950"
    label["payload"]["kg_produccion_ot"] = "8.750"
    label["payload"]["maquinista"] = "Cristóbal Lázaro"
    return label


def _post_weighing_assembly_label(code):
    label = _post_weighing_label(code)
    label["payload"].pop("of_ot", None)
    label["payload"]["oa_ot"] = "OA-000321 - OT-000777"
    label["payload"]["pieza_color"] = (
        "BASE ORG. #5 ARMADA - ASAS PLOMO"
    )
    return label


def _qr_size_dots(payload):
    qr_text = json.dumps(
        payload["qr"],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    qr = qrcode.QRCode(
        error_correction=ERROR_CORRECT_L,
        box_size=4,
        border=0,
    )
    qr.add_data(qr_text)
    qr.make(fit=True)
    return qr.modules_count * 4


def test_una_identidad_ocupa_ambas_columnas_como_copias_gemelas():
    tspl = ScmPrelabelService().generate_tspl(
        {"labels": [_label("OP0084-OT001-M001")]},
        printed_at=datetime(2026, 7, 28, 12, 30, tzinfo=timezone.utc),
    )

    assert "SIZE 109 mm, 50 mm" in tspl
    assert "GAP 3 mm, 0 mm" in tspl
    assert "OP0084-OT001-M001" in tspl
    assert "IMP.: 28/07/2026 07:30" in tspl
    assert "F.OT ORIG.: 2026-07-28" in tspl
    assert "MAQ.ORIG.: Juan Perez" in tspl
    assert "QRCODE 144" in tspl
    assert "QRCODE 584" in tspl
    assert ",L,4,A,0,M2," in tspl
    assert "TEXT 469" in tspl
    assert tspl.count("PRINT 1,1") == 1


def test_plantilla_v2_renderiza_of_ot_y_conserva_qr_v1():
    label = _canonical_label("OF000900-OT001-M001")
    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})
    svg = ScmPrelabelService().generate_preview_svg({"labels": [label]})

    assert "OF/OT: OF-000900 - OT-000001" in tspl
    assert "OP/OT:" not in tspl
    assert label["payload"]["qr"]["label_id"] in tspl
    assert "OF/OT: OF-000900 - OT-000001" in svg
    assert "F.OT ORIG.: 2026-07-28" in tspl
    assert "MAQ.ORIG.: Juan Perez" in tspl
    assert "F.OT ORIG.: 2026-07-28" in svg
    assert "MAQ.ORIG.: Juan Perez" in svg


def test_qr_json_usa_escape_de_comillas_nativo_tspl2():
    label = _canonical_label("OF000011-OT002-M030")
    label["payload"]["qr"]["verificacion"] = "Cristóbal"
    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})
    qr_text = json.dumps(
        label["payload"]["qr"],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    qr_commands = [
        line for line in tspl.splitlines() if line.startswith("QRCODE ")
    ]

    assert len(qr_commands) == 2
    assert all(
        command.count(r'\["]') == qr_text.count('"')
        for command in qr_commands
    )
    assert all(r'\"' not in command for command in qr_commands)
    printer_qr_text = (
        qr_commands[0].split(',M2,"', 1)[1][:-1]
        .replace(r'\["]', '"')
    )
    assert json.loads(printer_qr_text) == label["payload"]["qr"]


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


def test_dos_identidades_generan_dos_hojas_duplicadas():
    left = _label("OP0084-OT001-M001")
    right = deepcopy(_label("OP0084-OT001-M002"))
    tspl = ScmPrelabelService().generate_tspl({
        "labels": [left, right]
    })

    assert tspl.count("QRCODE") == 4
    assert tspl.count("PRINT 1,1") == 2
    assert "OP0084-OT001-M001" in tspl
    assert "OP0084-OT001-M002" in tspl
    assert left["payload"]["qr"]["label_id"] in tspl
    assert right["payload"]["qr"]["label_id"] in tspl


@pytest.mark.parametrize("labels", [
    [_label("OF0014-OT006-M009")],
    [_label("OF0014-OT006-M009"), _label("OF0014-OT006-M010")],
])
def test_tspl_termina_el_ultimo_print_con_crlf(labels):
    tspl = ScmPrelabelService().generate_tspl({"labels": labels})

    assert tspl.endswith("PRINT 1,1\r\n")


def test_preview_web_respeta_hoja_fisica_y_genera_qr():
    label = _label("OP0084-OT001-M001")
    svg = ScmPrelabelService().generate_preview_svg(
        {"labels": [label]},
        printed_at=datetime(2026, 7, 28, 12, 30, tzinfo=timezone.utc),
    )

    assert 'viewBox="0 0 872 400"' in svg
    assert 'width="109mm" height="50mm"' in svg
    assert "OP0084-OT001-M001" in svg
    assert "data:image/png;base64," in svg
    qr_size = _qr_size_dots(label["payload"])
    assert f'width="{qr_size}" height="{qr_size}"' in svg
    assert svg.count("OP0084-OT001-M001") == 2


def test_postpesaje_reserva_qr_y_declara_utf8_para_nombre_acentuado():
    label = _post_weighing_label("OF000900-OT001-M001")
    service = ScmPrelabelService()

    tspl = service.generate_tspl({"labels": [label]})
    svg = service.generate_preview_svg({"labels": [label]})

    qr_y_positions = [
        int(value)
        for value in re.findall(r"QRCODE \d+,(\d+),L,4,A,0,M2,", tspl)
    ]
    qr_size = _qr_size_dots(label["payload"])

    assert len(qr_y_positions) == 2
    assert all(y + qr_size <= 400 for y in qr_y_positions)
    assert "CODEPAGE UTF-8" in tspl
    assert "MAQ.ORIG.: Cristóbal Lázaro" in tspl
    assert "MAQ.ORIG.: Cristóbal Lázaro" in svg
    assert "Cristóbal Lázaro".encode("utf-8") in tspl.encode("utf-8")


def test_postpesaje_armado_declara_neto_total_sin_presentarlo_como_kg_ot():
    label = _post_weighing_assembly_label("OA000321-OT777-M001")
    service = ScmPrelabelService()

    tspl = service.generate_tspl({"labels": [label]})
    svg = service.generate_preview_svg({"labels": [label]})

    assert "NETO TOTAL ARM.: 8.950" in tspl
    assert "NETO TOTAL ARM.: 8.950" in svg
    assert "KG OT:" not in tspl
    assert "KG OT:" not in svg
    assert "KG FIS.:" not in tspl
    assert "KG FIS.:" not in svg


def test_postpesaje_fabricacion_conserva_peso_fisico_y_kg_ot():
    label = _post_weighing_label("OF000900-OT001-M001")
    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})

    assert "KG FIS.: 8.950" in tspl
    assert "KG OT: 8.750" in tspl
    assert "NETO TOTAL ARM.:" not in tspl


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


def test_fallo_de_acuse_reanuda_solo_central_sin_reimprimir(tmp_path):
    label = _label("OP0084-OT001-M001")
    job = {"print_job_id": str(uuid4()), "labels": [label]}

    class Central:
        def __init__(self):
            self.claims = 0
            self.acks = 0

        def claim_scm_print_job(self, _station_id, _job_id):
            self.claims += 1
            return job

        def acknowledge_scm_print_job(
            self, _station_id, _job_id, payload
        ):
            self.acks += 1
            if self.acks == 1:
                raise CentralApiError(
                    "CENTRAL_UNREACHABLE", "acuse no disponible"
                )
            return {"results": payload["results"]}

    class Printer:
        printer_name = "TSC"

        def __init__(self):
            self.calls = 0

        def print_tspl_result(self, payload):
            self.calls += 1
            byte_count = len(payload.encode("utf-8"))
            return PrinterEmissionResult(
                status=PrinterEmissionResult.ACCEPTED,
                expected_bytes=byte_count,
                bytes_written=byte_count,
                document_started=True,
                write_attempted=True,
            )

    database = tmp_path / "ack-retry.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_ID": "PESAJE-ACK-01",
        },
        start_workers=False,
    )
    central = Central()
    printer = Printer()
    try:
        with app.app_context():
            service = ScmPrelabelService(client=central, printer=printer)
            first = service.print_job(job["print_job_id"])
            second = service.print_job(job["print_job_id"])

            assert first["result"] == "IMPRESA"
            assert first["ack_pending"] is True
            assert first["central_ack_error"]["code"] == "CENTRAL_UNREACHABLE"
            assert second["result"] == "IMPRESA"
            assert second["ack_recovered"] is True
            assert second["already_printed"] is True
            assert second["ack_pending"] is False
            assert printer.calls == 1
            assert central.claims == 1
            assert central.acks == 2
            attempts = ScmLabelPrintAttempt.query.all()
            assert len(attempts) == 1
            assert attempts[0].result == "IMPRESA"
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_emision_en_progreso_tras_caida_se_vuelve_incierta_y_bloquea_retry(
    tmp_path,
):
    print_job_id = str(uuid4())
    label_id = str(uuid4())

    class Central:
        def __init__(self):
            self.acks = []

        def claim_scm_print_job(self, *_args, **_kwargs):
            raise AssertionError("No debe reclamar un trabajo incierto")

        def acknowledge_scm_print_job(
            self, _station_id, _job_id, payload
        ):
            self.acks.append(payload)
            return {"results": payload["results"]}

    class Printer:
        def print_tspl(self, _payload):
            raise AssertionError("No debe reimprimir un trabajo incierto")

    database = tmp_path / "interrupted-print.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_ID": "PESAJE-CRASH-01",
        },
        start_workers=False,
    )
    central = Central()
    try:
        with app.app_context():
            db.session.add(ScmLabelPrintAttempt(
                print_job_id=print_job_id,
                label_id=label_id,
                label_type="POSTPESAJE",
                payload_hash="a" * 64,
                result="EMISION_EN_PROGRESO",
            ))
            db.session.commit()

            result = ScmPrelabelService(
                client=central,
                printer=Printer(),
            ).print_job(print_job_id)

            attempt = ScmLabelPrintAttempt.query.one()
            assert attempt.result == "EMISION_INCIERTA"
            assert attempt.completed_at_utc is not None
            assert result["result"] == "EMISION_INCIERTA"
            assert result["auto_reprint_blocked"] is True
            assert result["ack_recovered"] is True
            assert central.acks[0]["results"][0]["estado"] == (
                "EMISION_INCIERTA"
            )
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_escritura_parcial_nunca_se_clasifica_sin_emision_ni_se_reimprime(
    tmp_path,
):
    label = _label("OP0084-OT001-M001")
    job = {"print_job_id": str(uuid4()), "labels": [label]}

    class Central:
        def __init__(self):
            self.claims = 0
            self.acks = 0

        def claim_scm_print_job(self, _station_id, _job_id):
            self.claims += 1
            return job

        def acknowledge_scm_print_job(self, *_args):
            self.acks += 1
            return {"estado": "PARCIAL"}

    class Printer:
        printer_name = "TSC"

        def __init__(self):
            self.calls = 0

        def print_tspl_result(self, payload):
            self.calls += 1
            expected = len(payload.encode("utf-8"))
            return PrinterEmissionResult(
                status=PrinterEmissionResult.UNCERTAIN,
                expected_bytes=expected,
                bytes_written=expected - 1,
                document_started=True,
                write_attempted=True,
                error="Escritura RAW incompleta",
            )

    database = tmp_path / "partial-write.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_ID": "PESAJE-PARTIAL-01",
        },
        start_workers=False,
    )
    central = Central()
    printer = Printer()
    try:
        with app.app_context():
            service = ScmPrelabelService(client=central, printer=printer)
            first = service.print_job(job["print_job_id"])
            second = service.print_job(job["print_job_id"])

            assert first["result"] == "EMISION_INCIERTA"
            assert first["auto_reprint_blocked"] is True
            assert first["printer_emission"]["bytes_written"] == (
                first["printer_emission"]["expected_bytes"] - 1
            )
            assert second["result"] == "EMISION_INCIERTA"
            assert second["ack_recovered"] is True
            assert printer.calls == 1
            assert central.claims == 1
            assert central.acks == 2
            assert ScmLabelPrintAttempt.query.one().result == (
                "EMISION_INCIERTA"
            )
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
