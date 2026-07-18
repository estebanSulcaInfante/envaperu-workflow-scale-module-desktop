import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError

from app import db
from app.models.pesaje import Pesaje


class CaptureValidationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class IdempotencyConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptureResult:
    pesaje: Pesaje
    created: bool


STRING_LIMITS = {
    "molde": 100,
    "maquina": 50,
    "nro_op": 20,
    "turno": 20,
    "nro_orden_trabajo": 20,
    "operador": 100,
    "color": 100,
    "pieza_sku": 50,
    "pieza_nombre": 100,
    "observaciones": 1000,
    "qr_data_original": 500,
}


def _decimal_value(raw, code, label):
    if isinstance(raw, bool):
        raise CaptureValidationError(code, f"{label} debe ser numerico")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CaptureValidationError(code, f"{label} debe ser numerico") from exc
    if not value.is_finite() or not math.isfinite(float(value)):
        raise CaptureValidationError(code, f"{label} debe ser finito")
    return value


def _canonical_decimal(value):
    normalized = value.normalize()
    return format(normalized, "f")


def normalize_capture_payload(payload, max_weight_kg):
    if not isinstance(payload, dict):
        raise CaptureValidationError("JSON_OBJECT_REQUIRED", "Se requiere un objeto JSON")

    weight = _decimal_value(payload.get("peso_kg"), "INVALID_WEIGHT", "peso_kg")
    if weight <= 0:
        raise CaptureValidationError("INVALID_WEIGHT", "peso_kg debe ser mayor que cero")
    if weight > Decimal(str(max_weight_kg)):
        raise CaptureValidationError(
            "WEIGHT_LIMIT_EXCEEDED",
            f"peso_kg excede el maximo tecnico de {max_weight_kg}",
        )

    strings = {}
    for field, limit in STRING_LIMITS.items():
        raw = payload.get(field)
        if raw is None:
            strings[field] = None
            continue
        if not isinstance(raw, str):
            raise CaptureValidationError(
                "INVALID_STRING",
                f"{field} debe ser texto",
            )
        value = raw.strip()
        if len(value) > limit:
            raise CaptureValidationError(
                "STRING_TOO_LONG",
                f"{field} excede {limit} caracteres",
            )
        strings[field] = value or None

    if not strings["nro_op"]:
        raise CaptureValidationError("OP_REQUIRED", "nro_op es requerido")

    fecha_ot = None
    raw_date = payload.get("fecha_orden_trabajo")
    if raw_date not in (None, ""):
        if not isinstance(raw_date, str):
            raise CaptureValidationError(
                "INVALID_DATE",
                "fecha_orden_trabajo debe usar YYYY-MM-DD",
            )
        try:
            fecha_ot = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise CaptureValidationError(
                "INVALID_DATE",
                "fecha_orden_trabajo debe usar YYYY-MM-DD",
            ) from exc

    unit_weight = None
    canonical_unit_weight = None
    raw_unit_weight = payload.get("peso_unitario_teorico")
    if raw_unit_weight not in (None, ""):
        unit_weight = _decimal_value(
            raw_unit_weight,
            "INVALID_UNIT_WEIGHT",
            "peso_unitario_teorico",
        )
        if unit_weight <= 0:
            raise CaptureValidationError(
                "INVALID_UNIT_WEIGHT",
                "peso_unitario_teorico debe ser mayor que cero",
            )
        canonical_unit_weight = _canonical_decimal(unit_weight)

    lote_salida_id = payload.get("lote_salida_pieza_color_id")
    if lote_salida_id is not None:
        if isinstance(lote_salida_id, bool):
            raise CaptureValidationError(
                "INVALID_LOTE_SALIDA",
                "lote_salida_pieza_color_id debe ser entero",
            )
        try:
            lote_salida_id = int(lote_salida_id)
        except (TypeError, ValueError) as exc:
            raise CaptureValidationError(
                "INVALID_LOTE_SALIDA",
                "lote_salida_pieza_color_id debe ser entero",
            ) from exc
        if lote_salida_id <= 0:
            raise CaptureValidationError(
                "INVALID_LOTE_SALIDA",
                "lote_salida_pieza_color_id debe ser positivo",
            )

    canonical = {
        "peso_kg": _canonical_decimal(weight),
        "fecha_orden_trabajo": fecha_ot.isoformat() if fecha_ot else None,
        "peso_unitario_teorico": canonical_unit_weight,
        "lote_salida_pieza_color_id": lote_salida_id,
        **strings,
    }
    payload_hash = hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()

    attributes = {
        "peso_kg": float(weight),
        "fecha_orden_trabajo": fecha_ot,
        "peso_unitario_teorico": (
            float(unit_weight) if unit_weight is not None else None
        ),
        "lote_salida_pieza_color_id": lote_salida_id,
        **strings,
    }
    return attributes, payload_hash


class CaptureService:
    def create(self, capture_id, payload, max_weight_kg):
        attributes, payload_hash = normalize_capture_payload(payload, max_weight_kg)
        existing = Pesaje.query.filter_by(capture_id=capture_id).one_or_none()
        if existing is not None:
            return self._existing_result(existing, payload_hash)

        pesaje = Pesaje(
            capture_id=capture_id,
            capture_payload_hash=payload_hash,
            **attributes,
        )
        db.session.add(pesaje)
        try:
            db.session.commit()
            return CaptureResult(pesaje=pesaje, created=True)
        except IntegrityError:
            db.session.rollback()
            existing = Pesaje.query.filter_by(capture_id=capture_id).one_or_none()
            if existing is None:
                raise
            return self._existing_result(existing, payload_hash)

    @staticmethod
    def _existing_result(existing, payload_hash):
        if existing.capture_payload_hash != payload_hash:
            raise IdempotencyConflict(existing.capture_id)
        return CaptureResult(pesaje=existing, created=False)
