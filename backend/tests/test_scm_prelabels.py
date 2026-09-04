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
from app.services.scm_prelabel_service import ScmPrelabelService


def _label(code):
    manga_id = str(uuid4())
    label_id = str(uuid4())
    payload = {
        "codigo_manga": code,
        "op_ot": "OP0084 - OT-000001",
        "fecha_ot": "2026-07-28",
        "maquinista": "Juan Perez",
        "operador": "Juan Perez",
        "maquina": "HT-360 A",
        "turno": "DIA",
        "pieza": "Asa fucsia",
        "pieza_color": "Asa fucsia (PC-000001)",
        "color": "FUCSIA SOLIDO",
        "tipo_manga": "Manga estandar",
        "cantidad_planificada_un": "100",
        "kg_estimados": "7.440",
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
    label["payload"]["template"] = {
        "version": "PREPESAJE_TSPL_5",
        "qr_contract": "LABEL_REF_V1",
    }
    label["payload"]["op"] = "OP0297"
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
    label["payload"].pop("qr")
    label["payload"]["document_type"] = "POSTPESAJE"
    label["payload"]["manga_id"] = str(uuid4())
    label["payload"]["cantidad_confirmada_un"] = "100"
    label["payload"]["fuente_cantidad"] = "PLAN_CONFIRMADO_POR_PESAJE"
    label["payload"]["kg_fisico"] = "8.950"
    label["payload"]["kg_produccion_ot"] = "8.750"
    label["payload"]["peso_neto_real_kg"] = "8.950"
    label["payload"]["peso_estandar_segun_unidades_kg"] = "8.750"
    label["payload"]["peso_fabricado_teorico_kg"] = "8.750"
    label["payload"]["aporte_desde_control_anterior_kg"] = "4.150"
    label["payload"]["maquinista"] = "Cristóbal Lázaro"
    return label


def _control_weight_label(code):
    label = _post_weighing_label(code)
    label["payload"].update({
        "document_type": "CONTROL_PESO",
        "cantidad_acumulada_un": "35",
        "peso_neto_real_kg": "8.950",
        "aporte_desde_control_anterior_kg": "4.150",
    })
    label["payload"].pop("cantidad_confirmada_un", None)
    label["payload"].pop("peso_fabricado_teorico_kg", None)
    label["payload"].pop("kg_produccion_ot", None)
    return label


def _post_weighing_assembly_label(code):
    label = _post_weighing_label(code)
    label["payload"].pop("of_ot", None)
    label["payload"]["oa_ot"] = "OA-000321 - OT-000777"
    label["payload"]["pieza_color"] = "BASE ORG. #5 ARMADA - ASAS PLOMO"
    label["payload"]["fuente_cantidad"] = "RESPONSABLE_ARMADO"
    return label


def _qr_size_dots(payload):
    qr_text = ScmPrelabelService._qr_text(payload)
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
    assert ",L,4,A,0," in tspl
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


def test_preetiqueta_generada_antes_del_contrato_compacto_conserva_qr_largo():
    label = _canonical_label("OF000900-OT001-M001")

    qr_text = ScmPrelabelService._qr_text(label["payload"])

    assert qr_text == json.dumps(
        label["payload"]["qr"],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_trabajo_color_conserva_contexto_autoritativo_fuera_del_qr():
    label = _color_work_label("OF000900-OT001-M001")
    authoritative_qr = deepcopy(label["payload"]["qr"])
    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})
    svg = ScmPrelabelService().generate_preview_svg({"labels": [label]})
    compact_qr = json.dumps(
        {"v": 1, "label_id": label["payload"]["qr"]["label_id"]},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert label["payload"]["of_ot"] == "OF-000900 - OT-000001"
    assert "OF/OT:" not in tspl
    assert "TC01" not in tspl
    assert ScmPrelabelService._qr_text(label["payload"]) == compact_qr
    assert label["payload"]["qr"]["manga_id"] not in tspl
    assert label["payload"]["trabajo_color"]["id"] not in tspl
    assert label["payload"]["qr"]["type"] not in tspl
    assert label["payload"]["qr"] == authoritative_qr
    assert "OF/OT:" not in svg


def test_qr_compacto_reduce_version_y_reserva_zona_silenciosa():
    label = _color_work_label("OF000900-OT001-M001")
    service = ScmPrelabelService()

    qr = service._qr_code(label["payload"])
    qr_text = service._qr_text(label["payload"])
    tspl = service.generate_tspl({"labels": [label]})

    assert qr.version == 4
    assert qr.modules_count == 33
    assert service.QR_GAP_Y == 4 * service.QR_MODULE_DOTS
    assert "QRCODE 158,240,L,4,A,0," in tspl
    assert qr_text.replace('"', '\\[\"]') in tspl
    assert '\\"label_id\\"' not in tspl


def test_preetiqueta_v5_aplica_identidad_separador_y_kg_teoricos():
    label = _color_work_label("OF000017-OT007-M003")
    service = ScmPrelabelService()

    tspl = service.generate_tspl(
        {"labels": [label]},
        printed_at=datetime(2026, 8, 31, 19, 50, tzinfo=timezone.utc),
    )
    svg = service.generate_preview_svg(
        {"labels": [label]},
        printed_at=datetime(2026, 8, 31, 19, 50, tzinfo=timezone.utc),
    )

    assert 'TEXT 31,10,"0",0,6,6,"MANGA:"' in tspl
    assert 'TEXT 99,4,"2",0,1,1,"OF000017-OT007-M003"' in tspl
    assert 'PZA: Asa fucsia' in tspl
    assert 'COLOR: FUCSIA SOLIDO' in tspl
    assert 'BAR 31,74,384,2' in tspl
    assert 'OP: OP0297' in tspl
    assert 'MAQUINA: HT-360 A' in tspl
    assert 'TIPO MANGA: Manga estandar' in tspl
    assert tspl.index('OP: OP0297') < tspl.index('MAQUINA: HT-360 A')
    assert tspl.index('MAQUINA: HT-360 A') < tspl.index(
        'TIPO MANGA: Manga estandar'
    )
    assert 'TURNO: DIA' in tspl
    assert 'F.OT ORIG.: 2026-07-28' in tspl
    assert 'OPE: Juan Perez' in tspl
    assert 'IMP: 31/08/2026 14:50' in tspl
    assert 'KG TEORICOS: 7.440 kg' in tspl
    assert "OF/OT:" not in tspl
    assert "CANT.:" not in tspl
    assert 'font-size="20"' in svg
    assert svg.count('font-size="16"') == 22

    scalable_sizes = re.findall(
        r'TEXT \d+,\d+,"0",0,(\d+),(\d+),',
        tspl,
    )
    assert set(scalable_sizes) == {("6", "6")}


def test_preetiqueta_v5_omite_fila_op_en_orden_excepcional():
    label = _color_work_label("OF000017-OT007-M003")
    label["payload"].pop("op")

    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})

    assert "OP:" not in tspl
    assert "PZA: Asa fucsia" in tspl


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


def test_postpesaje_no_crea_segundo_qr_y_declara_utf8_para_nombre_acentuado():
    label = _post_weighing_label("OF000900-OT001-M001")
    service = ScmPrelabelService()

    tspl = service.generate_tspl({"labels": [label]})
    svg = service.generate_preview_svg({"labels": [label]})

    assert "QRCODE" not in tspl
    assert "data:image/png;base64," not in svg
    assert "CODEPAGE UTF-8" in tspl
    assert "MAQUINISTA: Cristóbal Lázaro" in tspl
    assert "MAQUINISTA: Cristóbal Lázaro" in svg
    assert "Cristóbal Lázaro".encode("utf-8") in tspl.encode("utf-8")
    assert "CONTEO TEORICO: 100 UN" in tspl
    assert "CONTEO TEORICO: 100 UN" in svg
    assert "CONTEO FINAL" not in tspl


def test_postpesaje_armado_declara_peso_neto_final_sin_siglas_ambiguas():
    label = _post_weighing_assembly_label("OA000321-OT777-M001")
    service = ScmPrelabelService()

    tspl = service.generate_tspl({"labels": [label]})
    svg = service.generate_preview_svg({"labels": [label]})

    assert "PESO NETO FINAL (kg)" in tspl
    assert "PESO NETO FINAL (kg)" in svg
    assert '"8.95"' in tspl
    assert "KG OT:" not in tspl
    assert "KG OT:" not in svg
    assert "KG FIS.:" not in tspl
    assert "KG FIS.:" not in svg
    assert "CONTEO CONFIRMADO: 100 UN" in tspl
    assert "CONTEO CONFIRMADO: 100 UN" in svg


def test_postpesaje_v5_omite_peso_fabricado_si_no_hay_atribucion_actual():
    label = _post_weighing_assembly_label("OA000321-OT777-M001")
    label["payload"]["template"] = {"version": "POSTPESAJE_TSPL_5"}
    label["payload"].pop("peso_fabricado_teorico_kg", None)

    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})

    assert "PESO FABRICADO TEORICO" not in tspl


def test_postpesaje_v5_anterior_sin_fuente_no_afirma_conteo_fisico():
    label = _post_weighing_label("OF000900-OT001-M001")
    label["payload"].pop("fuente_cantidad")
    label["payload"]["template"] = {"version": "POSTPESAJE_TSPL_5"}

    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})

    assert "CONTEO TEORICO: 100 UN" in tspl
    assert "CONTEO FINAL" not in tspl


def test_postpesaje_fabricacion_distingue_neto_aporte_y_peso_fabricado():
    label = _post_weighing_label("OF000900-OT001-M001")
    service = ScmPrelabelService()
    tspl = service.generate_tspl({"labels": [label]})
    svg = service.generate_preview_svg({"labels": [label]})

    assert "PESO NETO FINAL (kg)" in tspl
    assert "APORTE ULTIMO TRAMO (kg)" in tspl
    assert "PESO FABRICADO TEORICO (kg): 8.75" in tspl
    assert 'TEXT 32,12,"2",0,1,1,"MANGA: OF000900-OT001-M001"' in tspl
    assert 'TEXT 86,108,"3",0,2,2,"8.95"' in tspl
    assert 'TEXT 310,244,"4",0,1,1,"+4.15"' in tspl
    assert 'font-size="48"' in svg
    assert 'font-size="32"' in svg
    assert ">8.95</text>" in svg
    assert ">+4.15</text>" in svg
    assert "8.950" not in tspl
    assert "4.150" not in tspl
    assert tspl.index("PESO FABRICADO TEORICO") < tspl.index(
        "APORTE ULTIMO TRAMO"
    )
    assert "PESO ESTANDAR SEGUN UNIDADES" not in tspl
    assert "KG FIS.:" not in tspl
    assert "KG OT:" not in tspl


def test_sticker_pesaje_redondea_solo_la_presentacion_a_dos_decimales():
    label = _post_weighing_label("OF000900-OT001-M001")
    label["payload"]["peso_neto_real_kg"] = "8.955"
    label["payload"]["aporte_desde_control_anterior_kg"] = "4.145"

    tspl = ScmPrelabelService().generate_tspl({"labels": [label]})

    assert '"8.96"' in tspl
    assert '"+4.15"' in tspl
    assert label["payload"]["peso_neto_real_kg"] == "8.955"
    assert label["payload"]["aporte_desde_control_anterior_kg"] == "4.145"


@pytest.mark.parametrize("labels", [
    [_control_weight_label("OF0014-OT006-M009")],
    [
        _control_weight_label("OF0014-OT006-M009"),
        _control_weight_label("OF0014-OT006-M010"),
    ],
])
def test_control_sin_qr_prioriza_neto_aporte_y_termina_con_crlf(labels):
    service = ScmPrelabelService()
    job = {"labels": labels}

    tspl = service.generate_tspl(job)
    svg = service.generate_preview_svg(job)

    assert "CONTROL · CONTINUA ABIERTA" in tspl
    assert "PESO NETO REAL (kg)" in tspl
    assert "APORTE DESDE CONTROL ANTERIOR (kg)" in tspl
    assert "PESO ESTANDAR SEGUN UNIDADES" not in tspl
    assert "QRCODE" not in tspl
    assert "data:image/png;base64," not in svg
    assert tspl.endswith("PRINT 1,1\r\n")


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
