from uuid import uuid4

import pytest

from app import create_app, db
from app.models.scm_label_print_attempt import ScmLabelPrintAttempt
from app.models.pesaje import Pesaje
from app.services.central_api_client import CentralApiClient, CentralApiError
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
        "cantidad_confirmada_un": "100",
        "kg_fisico": "10.000",
        "kg_produccion_ot": "10.000",
        "document_type": "POSTPESAJE",
        "manga_id": manga_id,
        "peso_neto_real_kg": "10.000",
        "peso_estandar_segun_unidades_kg": "10.000",
        "peso_fabricado_teorico_kg": "10.000",
        "aporte_desde_control_anterior_kg": "4.000",
    }
    return {
        "public_id": label_id,
        "payload_hash": "d" * 64,
        "payload": payload,
    }


def _control_label(label_id, manga_id):
    label = _post_label(label_id, manga_id)
    label["payload"].update({
        "document_type": "CONTROL_PESO",
        "cantidad_acumulada_un": None,
        "peso_neto_real_kg": "3.700",
        "peso_estandar_segun_unidades_kg": None,
        "aporte_desde_control_anterior_kg": "3.700",
    })
    label["payload"].pop("cantidad_confirmada_un", None)
    return label


def test_qr_legacy_no_entra_al_flujo_scm():
    with pytest.raises(ScmWeighingLocalError) as error:
        parse_scm_label_id("1;MOLDE;MAQUINA;OP0084")
    assert error.value.code == "LEGACY_QR_NOT_ACCEPTED"


def test_qr_compacto_resuelve_label_id_sin_contexto_duplicado():
    label_id = str(uuid4())

    assert parse_scm_label_id(
        f'{{"label_id":"{label_id}","v":1}}'
    ) == label_id


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


def test_resolve_publica_url_de_imagen_solo_desde_ruta_api_central(tmp_path):
    label_id = str(uuid4())

    class Central:
        origin = "https://central.example"

        def resolve_scm_manga_label(self, _label_id):
            return {
                "can_weigh": True,
                "manga": {
                    "codigo": "OF000001-OT001-M001",
                    "imagen_path": "/api/piezas-color/PC-000001/imagen",
                    "color_identidad": {
                        "id": 7,
                        "nombre": "TRANSPARENTE",
                        "base": {"id": 4, "nombre": "TRANSPARENTE"},
                        "familia": {"id": 3, "nombre": "TRANSPARENTE"},
                        "hex": "#EAF7F7",
                    },
                },
                "bloqueos_pesaje": {
                    "completar_final": None,
                    "registrar_avance_kg": {
                        "codigo": "MANGA_NO_HABILITADA",
                        "mensaje": "Control no disponible",
                        "recuperacion": "Solicite revisión en Central.",
                        "responsable": "CENTRAL",
                    },
                },
            }

    database = tmp_path / "image-context.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
        },
        start_workers=False,
    )
    try:
        with app.app_context():
            resolved = ScmWeighingService(client=Central()).resolve(label_id)
            assert resolved["manga"]["imagen_url"] == (
                "https://central.example/api/piezas-color/PC-000001/imagen"
            )
            assert resolved["manga"]["color_identidad"]["familia"]["nombre"] == (
                "TRANSPARENTE"
            )
            assert resolved["bloqueos_pesaje"] == Central().resolve_scm_manga_label(label_id)["bloqueos_pesaje"]
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_cliente_central_envia_control_a_endpoint_idempotente(monkeypatch):
    operation_id = str(uuid4())
    payload = {
        "label_id": str(uuid4()),
        "conteo_acumulado_un": "37",
        "motivo": "CAMBIO_TURNO",
    }
    captured = {}
    client = CentralApiClient(
        origin="https://central.envaperu.test",
        token="secret-token",
        station_version="1.1.0",
    )

    def fake_request(method, path, **kwargs):
        captured.update(method=method, path=path, **kwargs)
        return {"qr_preservado": True}

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.record_scm_manga_weighing_control(
        operation_id, payload
    ) == {"qr_preservado": True}
    assert captured == {
        "method": "POST",
        "path": "/api/integration/v1/manga-weighing-controls",
        "operation": "scm_manga_weighing_control",
        "payload": payload,
        "idempotency_key": operation_id,
    }


def test_route_local_expone_control_de_turno_con_motivo_default(tmp_path):
    operation_id = str(uuid4())
    label_id = str(uuid4())
    calls = []

    class Service:
        def record_control(self, **kwargs):
            calls.append(kwargs)
            return {
                "operation_id": kwargs["operation_id"],
                "control": {
                    "tipo": "AVANCE_KG",
                    "conteo_acumulado_un": None,
                },
                "produccion_confirmada_un": "0",
                "inventario_creado": False,
                "print_job_id": None,
                "qr_preservado": True,
            }

    database = tmp_path / "route-control.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "SCM_WEIGHING_SERVICE": Service(),
        },
        start_workers=False,
    )
    try:
        response = app.test_client().post(
            "/api/local/v1/scm/weighing/controls",
            headers={"Idempotency-Key": operation_id},
            json={"label_id": label_id},
        )

        assert response.status_code == 200
        assert response.get_json()["qr_preservado"] is True
        assert calls == [{
            "operation_id": operation_id,
            "label_id": label_id,
        }]
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_control_lee_balanza_imprime_sin_qr_y_no_crea_pesaje_local(tmp_path):
    operation_id = str(uuid4())
    label_id = str(uuid4())
    manga_id = str(uuid4())
    control_label_id = str(uuid4())
    print_job_id = str(uuid4())
    calls = []

    class Central:
        def resolve_scm_manga_label(self, requested_label_id):
            calls.append(("resolve", requested_label_id))
            return {
                "can_weigh": True,
                "can_register_weight_control": True,
                "manga": {
                    "public_id": label_id,
                    "tara_nominal_kg": "0.100",
                },
            }

        def record_scm_manga_weighing_control(self, requested_id, payload):
            calls.append(("control", requested_id, payload))
            return {
                "control": {
                    "tipo": "AVANCE_KG",
                    "conteo_acumulado_un": None,
                },
                "manga": {"estado": "EN_LLENADO"},
                "produccion_confirmada_un": "0",
                "inventario_creado": False,
                "print_job_id": print_job_id,
                "qr_preservado": True,
            }

        def claim_scm_print_job(self, _station_id, requested_job_id):
            calls.append(("claim_print", requested_job_id))
            return {
                "print_job_id": requested_job_id,
                "labels": [_control_label(control_label_id, manga_id)],
            }

        def acknowledge_scm_print_job(
            self, _station_id, requested_job_id, payload
        ):
            calls.append(("ack_print", requested_job_id, payload))
            return {"estado": "PROCESADO"}

    class Printer:
        printer_name = "TSC"

        def print_tspl(self, tspl):
            calls.append(("print", tspl))
            return True

    database = tmp_path / "control.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "SCM_OPERATOR_ID": "7",
        },
        start_workers=False,
    )
    try:
        with app.app_context():
            result = ScmWeighingService(
                client=Central(),
                printer=Printer(),
                scale_snapshot=lambda: {"peso_kg": 3.8, "stable": True},
            ).record_control(
                operation_id=operation_id,
                label_id=label_id,
            )

            assert [item[0] for item in calls] == [
                "resolve", "control", "claim_print", "print", "ack_print",
            ]
            control_payload = calls[1][2]
            assert control_payload["capture_id"] == operation_id
            assert control_payload["peso_bruto_kg"] == "3.800"
            assert control_payload["tara_kg"] == "0.100"
            assert control_payload["reading_stable"] is True
            assert control_payload["control_type"] == "AVANCE_KG"
            assert "conteo_acumulado_un" not in control_payload
            assert "motivo" not in control_payload
            assert result["produccion_confirmada_un"] == "0"
            assert result["inventario_creado"] is False
            assert result["print_job_id"] == print_job_id
            assert result["print_result"]["result"] == "IMPRESA"
            assert "PESO NETO REAL (kg)" in calls[3][1]
            assert "APORTE DESDE CONTROL ANTERIOR (kg)" in calls[3][1]
            assert "AVANCE EN KG" in calls[3][1]
            assert "CONTEO ACUMULADO" not in calls[3][1]
            assert "PESO ESTANDAR SEGUN UNIDADES" not in calls[3][1]
            assert "QRCODE" not in calls[3][1]
            assert result["qr_preservado"] is True
            assert Pesaje.query.count() == 0
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
                "can_register_weight_control": False,
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
            assert "cantidad_confirmada_un" not in confirm_payload
            assert "QRCODE" not in calls[3][1]
            assert "PESO NETO FINAL (kg)" in calls[3][1]
            assert "PESO FABRICADO TEORICO (kg): 10.000" in calls[3][1]
            assert Pesaje.query.count() == 0

            service.confirm(
                operation_id=str(uuid4()),
                label_id=prelabel_id,
                cantidad_confirmada_un="37",
                motivo_cierre_parcial="Cambio de turno",
            )
            partial_payload = [
                item[2] for item in calls if item[0] == "confirm"
            ][-1]
            assert partial_payload["cantidad_confirmada_un"] == "37"
            assert partial_payload["motivo_cierre_parcial"] == (
                "Cambio de turno"
            )
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_control_exige_capacidad_especifica_aunque_pesaje_final_este_habilitado(
    tmp_path,
):
    operation_id = str(uuid4())
    label_id = str(uuid4())

    class Central:
        def resolve_scm_manga_label(self, _label_id):
            return {
                "can_weigh": True,
                "can_register_shift_cut": False,
                "manga": {
                    "public_id": str(uuid4()),
                    "tara_nominal_kg": "0.100",
                },
            }

        def get_scm_operation(self, _operation_id):
            raise CentralApiError("CENTRAL_INCOMPATIBLE", "not found")

        def record_scm_manga_weighing_control(self, *_args, **_kwargs):
            raise AssertionError("No debe registrar un control no autorizado")

    database = tmp_path / "control-capability.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "SCM_OPERATOR_ID": "7",
        },
        start_workers=False,
    )
    try:
        with app.app_context(), pytest.raises(ScmWeighingLocalError) as error:
            ScmWeighingService(
                client=Central(),
                scale_snapshot=lambda: {
                    "peso_kg": 3.8,
                    "stable": True,
                },
                ).record_control(
                    operation_id=operation_id,
                    label_id=label_id,
                )
        assert error.value.code == "MANGA_NOT_READY"
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_reintento_control_recupera_resultado_sin_releer_ni_reenviar(tmp_path):
    operation_id = str(uuid4())
    label_id = str(uuid4())
    manga_id = str(uuid4())
    calls = []
    response = {
        "control": {
            "id": str(uuid4()),
            "manga_id": manga_id,
            "tipo": "AVANCE_KG",
            "conteo_acumulado_un": None,
        },
        "produccion_confirmada_un": "0",
        "inventario_creado": False,
        "print_job_id": None,
        "qr_preservado": True,
    }

    class Central:
        def resolve_scm_manga_label(self, _label_id):
            calls.append("resolve")
            return {
                "can_weigh": False,
                "can_register_weight_control": True,
                "manga": {
                    "public_id": manga_id,
                    "tara_nominal_kg": "0.100",
                },
            }

        def get_scm_operation(self, requested_id):
            calls.append(("recover", requested_id))
            return {
                "operation_id": requested_id,
                "status": 200,
                "response": response,
            }

        def record_scm_manga_weighing_control(self, *_args, **_kwargs):
            raise AssertionError("El replay no debe reenviar el control")

    database = tmp_path / "control-replay.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "SCM_OPERATOR_ID": "7",
        },
        start_workers=False,
    )
    try:
        with app.app_context():
            result = ScmWeighingService(
                client=Central(),
                scale_snapshot=lambda: (_ for _ in ()).throw(
                    AssertionError("El replay no debe releer la balanza")
                ),
                ).record_control(
                    operation_id=operation_id,
                    label_id=label_id,
                )
        assert calls == ["resolve", ("recover", operation_id)]
        assert result["control"]["conteo_acumulado_un"] is None
        assert result["control"]["tipo"] == "AVANCE_KG"
        assert result["recovered_operation"] is True
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_reintento_f2_recupera_confirmacion_y_no_duplica_impresion(tmp_path):
    operation_id = str(uuid4())
    label_id = str(uuid4())
    manga_id = str(uuid4())
    print_job_id = str(uuid4())
    calls = []
    response = {
        "weighing": {
            "manga_id": manga_id,
            "cantidad_confirmada": "50.000",
        },
        "print_job_id": print_job_id,
        "atribucion_turnos": [],
    }

    class Central:
        def resolve_scm_manga_label(self, _label_id):
            calls.append("resolve")
            return {
                "can_weigh": False,
                "can_register_shift_cut": False,
                "manga": {
                    "public_id": manga_id,
                    "tara_nominal_kg": "0.100",
                },
            }

        def get_scm_operation(self, requested_id):
            calls.append(("recover", requested_id))
            return {
                "operation_id": requested_id,
                "status": 200,
                "response": response,
            }

        def get_scm_print_job(self, _station_id, requested_job_id):
            calls.append(("fetch_print", requested_job_id))
            return {
                "print_job_id": requested_job_id,
                "status": "PRINTED",
                "labels": [],
            }

        def confirm_scm_manga_weighing(self, *_args, **_kwargs):
            raise AssertionError("El replay no debe reenviar el pesaje")

        def claim_scm_print_job(self, *_args, **_kwargs):
            raise AssertionError("El replay no debe reclamar ni reimprimir")

    class Printer:
        def print_tspl(self, _tspl):
            raise AssertionError("El replay no debe reimprimir")

    database = tmp_path / "final-replay.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_UUID": str(uuid4()),
            "SCM_OPERATOR_ID": "7",
        },
        start_workers=False,
    )
    try:
        with app.app_context():
            result = ScmWeighingService(
                client=Central(),
                printer=Printer(),
                scale_snapshot=lambda: (_ for _ in ()).throw(
                    AssertionError("El replay no debe releer la balanza")
                ),
            ).confirm(operation_id=operation_id, label_id=label_id)
        assert calls == [
            "resolve",
            ("recover", operation_id),
            ("fetch_print", print_job_id),
        ]
        assert result["recovered_operation"] is True
        assert result["print_result"]["result"] == "IMPRESA"
        assert result["print_result"]["already_printed"] is True
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_reintento_f2_no_reimprime_si_emision_local_fue_incierta(tmp_path):
    operation_id = str(uuid4())
    label_id = str(uuid4())
    manga_id = str(uuid4())
    print_job_id = str(uuid4())
    response = {
        "weighing": {"manga_id": manga_id},
        "print_job_id": print_job_id,
    }

    class Central:
        def resolve_scm_manga_label(self, _label_id):
            return {
                "can_weigh": False,
                "can_register_shift_cut": False,
                "manga": {
                    "public_id": manga_id,
                    "tara_nominal_kg": "0.100",
                },
            }

        def get_scm_operation(self, requested_id):
            return {"status": 200, "response": response}

        def get_scm_print_job(self, *_args, **_kwargs):
            raise AssertionError("La evidencia local incierta debe bloquear reimpresión")

    database = tmp_path / "uncertain-replay.db"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "STATION_UUID": str(uuid4()),
            "SCM_OPERATOR_ID": "7",
        },
        start_workers=False,
    )
    try:
        with app.app_context():
            db.session.add(ScmLabelPrintAttempt(
                print_job_id=print_job_id,
                label_id=str(uuid4()),
                label_type="POSTPESAJE",
                operation_id=operation_id,
                capture_id=operation_id,
                manga_id=manga_id,
                payload_hash="a" * 64,
                result="EMISION_INCIERTA",
            ))
            db.session.commit()
            result = ScmWeighingService(
                client=Central(),
                scale_snapshot=lambda: (_ for _ in ()).throw(
                    AssertionError("El replay no debe releer la balanza")
                ),
            ).confirm(operation_id=operation_id, label_id=label_id)
        assert result["print_result"] == {
            "result": "EMISION_INCIERTA",
            "recovered": True,
            "auto_reprint_blocked": True,
        }
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
