"""Impresión física explícita de stickers de la mesa mediante cola Windows RAW.

La vista previa/descarga no se considera impresión. El endpoint exige el nombre
de una cola seleccionada y solo informa éxito después de que Windows acepta el
trabajo RAW. Si falla después de comenzar la escritura, la emisión es incierta:
no se reintenta automáticamente para evitar duplicados físicos.
"""

from __future__ import annotations

import sqlite3

from flask import Response, current_app, jsonify, request

from mesa_inventory_sticker import render_sticker
from mesa_logging import log_event, log_peripheral_state


class PrinterUnavailable(RuntimeError):
    """No hay una cola Windows seleccionable o no está disponible."""


class PrinterEmissionUncertain(RuntimeError):
    """La cola pudo aceptar bytes; repetir automáticamente sería inseguro."""


class MesaPrinterService:
    def __init__(self, driver=None):
        self._driver_override = driver

    def _driver(self):
        if self._driver_override is not None:
            return self._driver_override
        try:
            import win32print
        except ImportError as error:
            raise PrinterUnavailable("La cola Windows no está disponible en este equipo.") from error
        return win32print

    def available_printers(self):
        try:
            driver = self._driver()
        except PrinterUnavailable:
            return []
        try:
            rows = driver.EnumPrinters(driver.PRINTER_ENUM_LOCAL | driver.PRINTER_ENUM_CONNECTIONS, None, 2)
            return [row["pPrinterName"] for row in rows if self._ready_queue(row)]
        except Exception:
            return []

    @staticmethod
    def _ready_queue(row):
        model = (str(row.get("pPrinterName", "")) + " " + str(row.get("pDriverName", ""))).upper()
        # Windows may retain an installed queue after the USB cable is removed.
        unavailable = 0x1 | 0x2 | 0x8 | 0x10 | 0x40 | 0x80 | 0x1000 | 0x100000 | 0x400000
        return ("TSC" in model or "TSPL" in model) and not (
            row.get("Status", 0) & unavailable or row.get("Attributes", 0) & 0x400)

    def status(self):
        configured = current_app.config.get("MESA_PRINTER_NAME") or current_app.config.get("PRINTER_NAME")
        available = self.available_printers()
        log_peripheral_state("tsc", "queue_available" if available else "no_available_queue", available=bool(available))
        return {
            "available": available,
            "configured": configured,
            "connected": bool(configured and configured in available),
            "windows_queue": bool(available),
        }

    def print_tspl(self, tspl: str, printer_name: str):
        if not isinstance(printer_name, str) or not printer_name.strip():
            raise PrinterUnavailable("Seleccione una impresora Windows antes de imprimir.")
        printer_name = printer_name.strip()
        if not isinstance(tspl, str) or not tspl.strip():
            raise ValueError("El trabajo TSPL está vacío.")
        try:
            driver = self._driver()
            handle = driver.OpenPrinter(printer_name)
        except PrinterUnavailable:
            raise
        except Exception as error:
            raise PrinterUnavailable(f"No se pudo abrir la cola Windows {printer_name}.") from error

        doc_started = False
        page_started = False
        emission_possible = False
        try:
            try:
                if not self._ready_queue(driver.GetPrinter(handle, 2)):
                    raise PrinterUnavailable("La cola TSC no está disponible. Revisa la impresora.")
                driver.StartDocPrinter(handle, 1, ("ENVAPERU mesa sticker", None, "RAW"))
                doc_started = True
                driver.StartPagePrinter(handle)
                page_started = True
                emission_possible = True
                payload = tspl.encode("utf-8")
                written = driver.WritePrinter(handle, payload)
                if written != len(payload):
                    raise OSError("Windows recibió un trabajo TSPL incompleto")
                driver.EndPagePrinter(handle)
                page_started = False
                driver.EndDocPrinter(handle)
                doc_started = False
                log_event("print_job", physical_status="queued", category="printer")
                return {"status": "QUEUED", "printer_name": printer_name}
            except Exception as error:
                if emission_possible:
                    log_event("print_job", physical_status="uncertain", category="printer", retryable=False)
                    raise PrinterEmissionUncertain(
                        "La impresora pudo aceptar el sticker. Revise físicamente antes de reintentar."
                    ) from error
                raise PrinterUnavailable(f"La cola Windows rechazó el trabajo: {error}") from error
        finally:
            if page_started:
                try:
                    driver.EndPagePrinter(handle)
                except Exception:
                    pass
            if doc_started:
                try:
                    driver.EndDocPrinter(handle)
                except Exception:
                    pass
            try:
                driver.ClosePrinter(handle)
            except Exception:
                pass


def _db_path():
    return current_app.config["MESA_DB_PATH"]


def return_label_data(codigo: str):
    """Obtiene el retorno ya confirmado sin convertirlo en un pesaje nuevo."""
    central = current_app.extensions.get("mesa_central")
    if central is not None:
        value = central.label(codigo, "retornos")
        return dict(value) if value else None
    connection = sqlite3.connect(str(_db_path()))
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT u.code AS codigo, u.piece AS pieza, u.color, r.net_kg AS neto
            FROM units u LEFT JOIN receipts r ON r.code = u.code
            WHERE u.code = ?
            """,
            (codigo,),
        ).fetchone()
        if row is None:
            return None
        return {**dict(row), "zona": "Retorno de armado", "bruto": None, "tara": None}
    finally:
        connection.close()


def _printer(app):
    service = app.extensions.get("mesa_printer_service")
    if service is None:
        service = MesaPrinterService()
        app.extensions["mesa_printer_service"] = service
    return service


def _error_response(error, preview_url):
    if isinstance(error, PrinterEmissionUncertain):
        return jsonify(
            error=str(error), code="EMISSION_UNCERTAIN", recoverable=True,
            safe_to_retry=False, preview_url=preview_url,
        ), 503
    if isinstance(error, PrinterUnavailable):
        return jsonify(
            error=str(error), code="PRINTER_UNAVAILABLE", recoverable=True,
            safe_to_retry=True, preview_url=preview_url,
        ), 503
    return jsonify(error=str(error), code="PRINTER_ERROR", recoverable=True, preview_url=preview_url), 500


def register_printer_routes(app):
    """Registra estado, previews de retorno y POSTs de impresión física."""
    _printer(app)

    @app.get("/api/mesa/printer/status")
    def printer_status():
        return jsonify(_printer(app).status())

    @app.post("/api/mesa/inventario/etiquetas/<codigo>/<kind>/print")
    @app.post("/api/mesa/inventario/etiquetas/<codigo>/<kind>/imprimir")
    def print_inventory_label(codigo, kind):
        central = app.extensions.get("mesa_central")
        if central is not None:
            unit = central.label(codigo, "inventario")
            unit = dict(unit) if unit else None
        else:
            from mesa_inventory import label_data
            unit = label_data(codigo, db_path=app.config["MESA_DB_PATH"])
        if unit is None:
            return jsonify(error="Identidad no encontrada"), 404
        payload = request.get_json(silent=True) or {}
        printer_name = payload.get("printer_name")
        preview = f"/api/mesa/inventario/etiquetas/{codigo}/{kind}.svg?formato=50x50"
        try:
            tspl = render_sticker(unit, kind, "50x50", "tspl")
            result = _printer(app).print_tspl(tspl, printer_name)
            copies = 1 if kind == "identidad" else 2
            return jsonify(**result, copies=copies, codigo=codigo, kind=kind, preview_url=preview), 202
        except (ValueError, PrinterUnavailable, PrinterEmissionUncertain) as error:
            if isinstance(error, ValueError):
                return jsonify(error=str(error)), 422
            return _error_response(error, preview)

    @app.get("/api/mesa/retornos/etiquetas/<codigo>.<output>")
    def return_label(codigo, output):
        unit = return_label_data(codigo)
        if unit is None:
            return jsonify(error="Retorno no encontrado"), 404
        try:
            kind = "retorno" if unit.get("neto") is not None else "identidad"
            content = render_sticker(unit, kind, request.args.get("formato", "50x50"), output)
        except ValueError as error:
            return jsonify(error=str(error)), 422
        if output == "svg":
            return Response(content, mimetype="image/svg+xml", headers={"Cache-Control": "no-store"})
        return Response(content.encode("utf-8"), mimetype="application/octet-stream")

    @app.post("/api/mesa/retornos/etiquetas/<codigo>/print")
    @app.post("/api/mesa/retornos/etiquetas/<codigo>/imprimir")
    def print_return_label(codigo):
        unit = return_label_data(codigo)
        if unit is None:
            return jsonify(error="Retorno no encontrado"), 404
        payload = request.get_json(silent=True) or {}
        preview = f"/api/mesa/retornos/etiquetas/{codigo}.svg?formato=50x50"
        try:
            kind = "retorno" if unit.get("neto") is not None else "identidad"
            result = _printer(app).print_tspl(render_sticker(unit, kind, "50x50", "tspl"), payload.get("printer_name"))
            copies = 1 if kind == "identidad" else 2
            return jsonify(**result, copies=copies, codigo=codigo, kind=kind, preview_url=preview), 202
        except (ValueError, PrinterUnavailable, PrinterEmissionUncertain) as error:
            if isinstance(error, ValueError):
                return jsonify(error=str(error)), 422
            return _error_response(error, preview)


__all__ = [
    "MesaPrinterService", "PrinterEmissionUncertain", "PrinterUnavailable",
    "register_printer_routes", "return_label_data",
]
