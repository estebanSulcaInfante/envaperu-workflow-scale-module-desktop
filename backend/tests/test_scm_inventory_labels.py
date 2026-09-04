from uuid import uuid4

from app import create_app, db
from app.models.scm_label_print_attempt import ScmLabelPrintAttempt
from app.services.scm_inventory_label_service import (
    InventoryLabelError,
    ScmInventoryLabelService,
)


def _unit():
    unit_id = str(uuid4())
    return {
        "id": unit_id,
        "codigo": "UL-20260824-001",
        "qr_value": f"SCM:UL:{unit_id}",
        "articulo_codigo": "MP-PP-CLARIFICADO",
        "articulo_nombre": "PP clarificado",
        "ubicacion_codigo": "A-ENVA-MP-GEN",
        "estado_calidad": "LIBERADO",
        "peso_bruto_kg": "25.100",
        "tara_kg": "0.100",
        "peso_neto_kg": "25.000",
        "created_at": "2026-08-24T15:30:00-05:00",
    }


def test_tspl_y_preview_comparten_layout_fisico_y_qr_real():
    unit = _unit()
    service = ScmInventoryLabelService()

    tspl = service.generate_tspl(unit)
    svg = service.generate_preview_svg(unit)

    assert "SIZE 109 mm, 50 mm" in tspl
    assert "GAP 3 mm, 0 mm" in tspl
    assert "UNIDAD: UL-20260824-001" in tspl
    assert "NET: 25.000 kg" in tspl
    assert unit["qr_value"] in tspl
    assert tspl.count("QRCODE") == 1
    assert 'viewBox="0 0 872 400"' in svg
    assert 'width="109mm" height="50mm"' in svg
    assert "UL-20260824-001" in svg
    assert "data:image/png;base64," in svg
    assert "COLUMNA LIBRE" in svg


def test_rechaza_qr_o_pesos_que_no_corresponden_a_la_unidad():
    unit = _unit()
    unit["qr_value"] = f"SCM:UL:{uuid4()}"

    try:
        ScmInventoryLabelService().generate_tspl(unit)
    except InventoryLabelError as exc:
        assert exc.code == "INVALID_LOGISTIC_UNIT_QR"
    else:
        raise AssertionError("Debio rechazar el QR de otra unidad")

    unit = _unit()
    unit["peso_neto_kg"] = "24.000"
    try:
        ScmInventoryLabelService().generate_tspl(unit)
    except InventoryLabelError as exc:
        assert exc.code == "INCONSISTENT_LOGISTIC_UNIT_WEIGHT"
    else:
        raise AssertionError("Debio rechazar pesos inconsistentes")


def test_impresion_simulada_conserva_evidencia_tecnica_local(tmp_path):
    class Printer:
        printer_name = "TSC-UAT"

        def __init__(self):
            self.payloads = []

        def print_tspl(self, payload):
            self.payloads.append(payload)
            return True

    database = tmp_path / "pesajes.db"
    printer = Printer()
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SIMULATE_PRINTER": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
        },
        start_workers=False,
    )
    try:
        operation_id = str(uuid4())
        with app.app_context():
            service = ScmInventoryLabelService(printer=printer)
            unit = _unit()
            result = service.print_label(unit, operation_id=operation_id)
            replay = service.print_label(unit, operation_id=operation_id)
            attempt = ScmLabelPrintAttempt.query.one()

            assert result["result"] == "SIMULADA"
            assert result["simulated"] is True
            assert len(printer.payloads) == 1
            assert replay["replayed"] is True
            assert len(printer.payloads) == 1
            assert attempt.print_job_id == operation_id
            assert attempt.label_type == "INVENTARIO_APERTURA"
            assert attempt.result == "SIMULADA"
            assert len(attempt.payload_hash) == 64
            assert len(attempt.rendered_payload_hash) == 64
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_endpoints_preview_e_impresion_no_confunden_simulacion(tmp_path):
    class Service:
        def __init__(self):
            self.print_calls = []

        def preview(self, unit):
            assert unit["codigo"] == "UL-20260824-001"
            return {
                "template_version": "INVENTARIO_APERTURA_TSPL_1",
                "tspl": "SIZE 109 mm, 50 mm",
                "preview_svg": "<svg/>",
            }

        def print_label(self, unit, *, operation_id):
            self.print_calls.append((unit, operation_id))
            return {
                "template_version": "INVENTARIO_APERTURA_TSPL_1",
                "result": "SIMULADA",
                "simulated": True,
                "preview_svg": "<svg/>",
            }

    database = tmp_path / "pesajes.db"
    service = Service()
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SYNC_ENABLED": False,
            "MONITORING_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "STATION_DATABASE_PATH": str(database),
            "STATION_BACKUP_DIR": str(tmp_path / "backups"),
            "SCM_INVENTORY_LABEL_SERVICE": service,
        },
        start_workers=False,
    )
    try:
        client = app.test_client()
        unit = _unit()
        preview = client.post(
            "/api/local/v1/scm/inventory-opening/labels/preview",
            json={"unit": unit},
        )
        operation_id = str(uuid4())
        printed = client.post(
            "/api/local/v1/scm/inventory-opening/labels/print",
            json={"unit": unit},
            headers={"Idempotency-Key": operation_id},
        )

        assert preview.status_code == 200
        assert preview.get_json()["preview_svg"] == "<svg/>"
        assert printed.status_code == 200
        assert printed.get_json()["result"] == "SIMULADA"
        assert service.print_calls == [(unit, operation_id)]
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
