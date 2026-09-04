"""Renderiza e imprime stickers TSPL de unidades de apertura física."""

import base64
import hashlib
import io
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape

import qrcode
from flask import current_app, has_app_context

from app import db
from app.models.scm_label_print_attempt import ScmLabelPrintAttempt
from app.services.printer_service import get_printer_service
from app.services.scm_prelabel_service import _station_timezone


class InventoryLabelError(ValueError):
    def __init__(self, code, message, *, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _text(value, *, field, limit=120):
    normalized = str(value or "").strip()
    if not normalized:
        raise InventoryLabelError(
            "INVALID_LOGISTIC_UNIT",
            f"La unidad no contiene {field}.",
        )
    return normalized[:limit]


def _weight(value, *, field):
    try:
        normalized = Decimal(str(value)).quantize(Decimal("0.001"))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise InventoryLabelError(
            "INVALID_LOGISTIC_UNIT_WEIGHT",
            f"El campo {field} no contiene un peso valido.",
        ) from error
    if normalized < 0:
        raise InventoryLabelError(
            "INVALID_LOGISTIC_UNIT_WEIGHT",
            f"El campo {field} no puede ser negativo.",
        )
    return normalized


def _tspl_quoted(value, limit=600):
    return str(value or "")[:limit].replace("\\", "\\\\").replace('"', '\\"')


def _safe(value, limit=44):
    return str(value or "").replace('"', "'")[:limit]


class ScmInventoryLabelService:
    """Una sola definicion de filas alimenta TSPL y vista previa SVG."""

    TEMPLATE_VERSION = "INVENTARIO_APERTURA_TSPL_1"
    LEFT_X = 24
    RIGHT_X = 464
    STICKER_WIDTH = 400
    LINE_HEIGHT = 22

    def __init__(self, *, printer=None):
        self.printer = printer

    @staticmethod
    def _timezone_name():
        if has_app_context():
            return current_app.config.get("TIMEZONE", "America/Lima")
        return "America/Lima"

    @staticmethod
    def _normalize(unit):
        if not isinstance(unit, dict):
            raise InventoryLabelError(
                "INVALID_LOGISTIC_UNIT", "La unidad logistica no es valida."
            )
        try:
            unit_id = str(uuid.UUID(str(unit.get("id"))))
        except (TypeError, ValueError, AttributeError) as error:
            raise InventoryLabelError(
                "INVALID_LOGISTIC_UNIT", "La unidad no posee un UUID valido."
            ) from error

        qr_value = _text(unit.get("qr_value"), field="qr_value", limit=100)
        if qr_value != f"SCM:UL:{unit_id}":
            raise InventoryLabelError(
                "INVALID_LOGISTIC_UNIT_QR",
                "El QR no corresponde a la unidad logistica seleccionada.",
            )

        gross = _weight(unit.get("peso_bruto_kg"), field="peso_bruto_kg")
        tare = _weight(unit.get("tara_kg"), field="tara_kg")
        net = _weight(unit.get("peso_neto_kg"), field="peso_neto_kg")
        if net <= 0 or gross - tare != net:
            raise InventoryLabelError(
                "INCONSISTENT_LOGISTIC_UNIT_WEIGHT",
                "Los pesos bruto, tara y NET de la unidad no son consistentes.",
            )

        return {
            "id": unit_id,
            "codigo": _text(unit.get("codigo"), field="codigo", limit=48),
            "qr_value": qr_value,
            "articulo_codigo": _text(
                unit.get("articulo_codigo"), field="articulo_codigo", limit=48
            ),
            "articulo_nombre": _text(
                unit.get("articulo_nombre"), field="articulo_nombre", limit=80
            ),
            "ubicacion_codigo": _text(
                unit.get("ubicacion_codigo"), field="ubicacion_codigo", limit=48
            ),
            "estado_calidad": _text(
                unit.get("estado_calidad"), field="estado_calidad", limit=32
            ).upper(),
            "peso_bruto_kg": format(gross, "f"),
            "tara_kg": format(tare, "f"),
            "peso_neto_kg": format(net, "f"),
            "created_at": str(unit.get("created_at") or "").strip(),
        }

    @staticmethod
    def _local_time(value):
        if not value:
            return "SIN FECHA"
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            zone = _station_timezone(ScmInventoryLabelService._timezone_name())
            return parsed.astimezone(zone).strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError):
            return _safe(value, 24)

    def _rows(self, unit, printed_at):
        normalized = self._normalize(unit)
        local_printed = printed_at.astimezone(
            _station_timezone(self._timezone_name())
        ).strftime("%d/%m/%Y %H:%M")
        return normalized, [
            ("UNIDAD", normalized["codigo"]),
            ("MATERIAL", normalized["articulo_codigo"]),
            ("NOMBRE", normalized["articulo_nombre"]),
            ("NET", f'{normalized["peso_neto_kg"]} kg'),
            ("BRUTO", f'{normalized["peso_bruto_kg"]} kg'),
            ("TARA", f'{normalized["tara_kg"]} kg'),
            ("UBIC.", normalized["ubicacion_codigo"]),
            ("CALIDAD", normalized["estado_calidad"]),
            ("CAP.", self._local_time(normalized["created_at"])),
            ("IMP.", local_printed),
        ]

    def _tspl_column(self, x, unit, printed_at):
        normalized, rows = self._rows(unit, printed_at)
        y = 22
        commands = [f"BAR {x},18,{self.STICKER_WIDTH},3"]
        for label, value in rows:
            commands.append(
                f'TEXT {x + 5},{y},"1",0,1,1,"{label}: {_safe(value)}"'
            )
            y += self.LINE_HEIGHT
        commands.extend((
            f"BAR {x},{y},{self.STICKER_WIDTH},2",
            f'QRCODE {x + 120},{y + 8},L,4,A,0,"{_tspl_quoted(normalized["qr_value"])}"',
        ))
        return "\n".join(commands)

    @staticmethod
    def _qr_data_uri(qr_value):
        image = qrcode.make(qr_value)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(
            buffer.getvalue()
        ).decode("ascii")

    def _svg_column(self, x, unit, printed_at):
        normalized, rows = self._rows(unit, printed_at)
        y = 34
        parts = [
            f'<rect x="{x}" y="18" width="{self.STICKER_WIDTH}" '
            'height="364" rx="4" fill="white" stroke="#111" stroke-width="2"/>',
        ]
        for label, value in rows:
            parts.append(
                f'<text x="{x + 7}" y="{y}" font-family="Arial, sans-serif" '
                f'font-size="13" font-weight="600">'
                f'{escape(f"{label}: {_safe(value)}")}</text>'
            )
            y += self.LINE_HEIGHT
        parts.extend((
            f'<line x1="{x}" y1="{y}" x2="{x + self.STICKER_WIDTH}" '
            f'y2="{y}" stroke="#111" stroke-width="2"/>',
            f'<image href="{self._qr_data_uri(normalized["qr_value"])}" '
            f'x="{x + 120}" y="{y + 7}" width="120" height="120"/>',
        ))
        return "".join(parts)

    def generate_tspl(self, unit, *, printed_at=None):
        actual_printed_at = printed_at or datetime.now(timezone.utc)
        column = self._tspl_column(self.LEFT_X, unit, actual_printed_at)
        return "\n".join((
            "SIZE 109 mm, 50 mm",
            "GAP 3 mm, 0 mm",
            "SET REFERENCE 0,0",
            "DIRECTION 1",
            "SET TEAR ON",
            "OFFSET 0 mm",
            "CLS",
            column,
            "PRINT 1,1",
        ))

    def generate_preview_svg(self, unit, *, printed_at=None):
        actual_printed_at = printed_at or datetime.now(timezone.utc)
        column = self._svg_column(self.LEFT_X, unit, actual_printed_at)
        empty = (
            '<rect x="464" y="18" width="400" height="364" rx="4" '
            'fill="#f7f7f7" stroke="#aaa" stroke-dasharray="8 8"/>'
            '<text x="664" y="200" text-anchor="middle" '
            'font-family="Arial" font-size="18" fill="#777">COLUMNA LIBRE</text>'
        )
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 872 400" width="109mm" height="50mm" '
            'role="img" aria-label="Sticker TSPL de unidad logistica">'
            '<rect width="872" height="400" fill="#e9edf2"/>'
            + column + empty + "</svg>"
        )

    def preview(self, unit):
        printed_at = datetime.now(timezone.utc)
        return {
            "template_version": self.TEMPLATE_VERSION,
            "tspl": self.generate_tspl(unit, printed_at=printed_at),
            "preview_svg": self.generate_preview_svg(unit, printed_at=printed_at),
        }

    def print_label(self, unit, *, operation_id):
        try:
            operation_id = str(uuid.UUID(str(operation_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise InventoryLabelError(
                "INVALID_IDEMPOTENCY_KEY",
                "La impresion requiere una Idempotency-Key UUID valida.",
            ) from error

        normalized = self._normalize(unit)
        existing = ScmLabelPrintAttempt.query.filter_by(
            operation_id=operation_id,
            label_type="INVENTARIO_APERTURA",
        ).one_or_none()
        if existing is not None:
            if existing.label_id != normalized["id"]:
                raise InventoryLabelError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "La Idempotency-Key ya pertenece a otra unidad logistica.",
                    status=409,
                )
            return {
                "template_version": self.TEMPLATE_VERSION,
                "result": existing.result,
                "simulated": existing.result == "SIMULADA",
                "printer_name": existing.printer_name,
                "error": existing.error_detail,
                "preview_svg": self.generate_preview_svg(normalized),
                "print_attempt": existing.to_dict(),
                "replayed": True,
            }

        attempted_at = datetime.now(timezone.utc)
        tspl = self.generate_tspl(normalized, printed_at=attempted_at)
        preview_svg = self.generate_preview_svg(normalized, printed_at=attempted_at)
        payload_hash = hashlib.sha256(json.dumps(
            normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        rendered_hash = hashlib.sha256(tspl.encode("utf-8")).hexdigest()
        printer = self.printer or current_app.config.get(
            "SCM_INVENTORY_LABEL_PRINTER"
        ) or get_printer_service()
        printer_name = getattr(printer, "printer_name", None) or current_app.config.get(
            "PRINTER_NAME"
        )
        simulated = bool(current_app.config.get("SIMULATE_PRINTER", False))
        try:
            success = bool(printer.print_tspl(tspl))
            if success:
                result = "SIMULADA" if simulated else "IMPRESA"
                error = None
            else:
                result = "FALLIDA_SIN_EMISION"
                error = "La impresora rechazo el trabajo"
        except Exception as exc:
            result = "EMISION_INCIERTA"
            error = str(exc)[:500]

        completed_at = datetime.now(timezone.utc)
        attempt = ScmLabelPrintAttempt(
            print_job_id=operation_id,
            label_id=normalized["id"],
            label_type="INVENTARIO_APERTURA",
            operation_id=operation_id,
            capture_id=normalized["id"],
            payload_hash=payload_hash,
            rendered_payload_hash=rendered_hash,
            attempted_at_utc=attempted_at,
            completed_at_utc=completed_at,
            printer_name=printer_name,
            result=result,
            error_detail=error,
        )
        db.session.add(attempt)
        db.session.commit()
        return {
            "template_version": self.TEMPLATE_VERSION,
            "result": result,
            "simulated": simulated,
            "printer_name": printer_name,
            "error": error,
            "preview_svg": preview_svg,
            "print_attempt": attempt.to_dict(),
            "replayed": False,
        }


def get_scm_inventory_label_service():
    configured = current_app.config.get("SCM_INVENTORY_LABEL_SERVICE")
    return configured or ScmInventoryLabelService()
