import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError

from app import db
from app.models.pesaje_correction_request import PesajeCorrectionRequest


class CorrectionValidationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class CorrectionIdempotencyConflict(RuntimeError):
    pass


class PesajeAlreadyVoid(RuntimeError):
    pass


@dataclass(frozen=True)
class CorrectionCreateResult:
    request: PesajeCorrectionRequest
    created: bool


STRING_CHANGE_LIMITS = {
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
}
SUPPORTED_CHANGES = set(STRING_CHANGE_LIMITS) | {
    "peso_kg",
    "peso_unitario_teorico",
    "fecha_orden_trabajo",
}
SNAPSHOT_FIELDS = (
    "id",
    "peso_kg",
    "peso_bruto_kg",
    "fraccion_descuento",
    "fecha_hora",
    "molde",
    "maquina",
    "nro_op",
    "turno",
    "fecha_orden_trabajo",
    "nro_orden_trabajo",
    "peso_unitario_teorico",
    "operador",
    "color",
    "lote_salida_pieza_color_id",
    "capture_id",
    "pieza_sku",
    "pieza_nombre",
    "observaciones",
    "sincronizado",
    "fecha_sincronizacion",
    "deleted_at",
)


def _required_string(payload, field, code, limit):
    raw = payload.get(field)
    if not isinstance(raw, str) or not raw.strip():
        raise CorrectionValidationError(code, f"{field} es requerido")
    value = raw.strip()
    if len(value) > limit:
        raise CorrectionValidationError(
            "STRING_TOO_LONG",
            f"{field} excede {limit} caracteres",
        )
    return value


def _optional_string(payload, field, limit):
    raw = payload.get(field)
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        raise CorrectionValidationError("INVALID_STRING", f"{field} debe ser texto")
    value = raw.strip()
    if len(value) > limit:
        raise CorrectionValidationError(
            "STRING_TOO_LONG",
            f"{field} excede {limit} caracteres",
        )
    return value or None


def _decimal(raw, field, allow_none=False):
    if raw is None and allow_none:
        return None
    if isinstance(raw, bool):
        raise CorrectionValidationError("INVALID_WEIGHT", f"{field} debe ser numerico")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CorrectionValidationError(
            "INVALID_WEIGHT",
            f"{field} debe ser numerico",
        ) from exc
    if not value.is_finite() or value <= 0:
        raise CorrectionValidationError(
            "INVALID_WEIGHT",
            f"{field} debe ser mayor que cero",
        )
    if value.as_tuple().exponent < -3:
        raise CorrectionValidationError(
            "WEIGHT_PRECISION_EXCEEDED",
            f"{field} admite maximo tres decimales",
        )
    return format(value.quantize(Decimal("0.001")), "f")


def _normalize_changes(raw_changes, action, max_weight_kg):
    if not isinstance(raw_changes, dict):
        raise CorrectionValidationError(
            "CHANGES_OBJECT_REQUIRED",
            "proposed_changes debe ser un objeto JSON",
        )
    if action == PesajeCorrectionRequest.ACTION_CORRECT and not raw_changes:
        raise CorrectionValidationError(
            "CHANGES_REQUIRED",
            "CORRECT requiere al menos un cambio propuesto",
        )
    if action == PesajeCorrectionRequest.ACTION_VOID and raw_changes:
        raise CorrectionValidationError(
            "CHANGES_NOT_ALLOWED",
            "VOID no acepta cambios de campos",
        )

    unknown = sorted(set(raw_changes) - SUPPORTED_CHANGES)
    if unknown:
        raise CorrectionValidationError(
            "UNSUPPORTED_CHANGE",
            f"Campo no corregible: {unknown[0]}",
        )

    normalized = {}
    for field in sorted(raw_changes):
        raw = raw_changes[field]
        if field == "peso_kg":
            value = _decimal(raw, field)
            if Decimal(value) > Decimal(str(max_weight_kg)):
                raise CorrectionValidationError(
                    "WEIGHT_LIMIT_EXCEEDED",
                    f"peso_kg excede el maximo tecnico de {max_weight_kg}",
                )
            normalized[field] = value
        elif field == "peso_unitario_teorico":
            normalized[field] = _decimal(raw, field, allow_none=True)
        elif field == "fecha_orden_trabajo":
            if raw in (None, ""):
                normalized[field] = None
            elif not isinstance(raw, str):
                raise CorrectionValidationError(
                    "INVALID_DATE",
                    "fecha_orden_trabajo debe usar YYYY-MM-DD",
                )
            else:
                try:
                    normalized[field] = date.fromisoformat(raw).isoformat()
                except ValueError as exc:
                    raise CorrectionValidationError(
                        "INVALID_DATE",
                        "fecha_orden_trabajo debe usar YYYY-MM-DD",
                    ) from exc
        else:
            limit = STRING_CHANGE_LIMITS[field]
            if raw is None:
                normalized[field] = None
            elif not isinstance(raw, str):
                raise CorrectionValidationError(
                    "INVALID_STRING",
                    f"{field} debe ser texto",
                )
            else:
                value = raw.strip()
                if len(value) > limit:
                    raise CorrectionValidationError(
                        "STRING_TOO_LONG",
                        f"{field} excede {limit} caracteres",
                    )
                normalized[field] = value or None
    return normalized


def _serialize_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def snapshot_pesaje(pesaje):
    return {
        field: _serialize_value(getattr(pesaje, field))
        for field in SNAPSHOT_FIELDS
    }


def _original_value(pesaje, field):
    value = getattr(pesaje, field)
    if field in {"peso_kg", "peso_unitario_teorico"} and value is not None:
        return format(Decimal(str(value)).quantize(Decimal("0.001")), "f")
    return _serialize_value(value)


def normalize_correction_payload(pesaje, payload, max_weight_kg):
    if not isinstance(payload, dict):
        raise CorrectionValidationError(
            "JSON_OBJECT_REQUIRED",
            "Se requiere un objeto JSON",
        )
    action = str(payload.get("action", "")).strip().upper()
    if action not in {
        PesajeCorrectionRequest.ACTION_CORRECT,
        PesajeCorrectionRequest.ACTION_VOID,
    }:
        raise CorrectionValidationError(
            "INVALID_ACTION",
            "action debe ser CORRECT o VOID",
        )

    requested_by = _required_string(
        payload,
        "requested_by",
        "REQUESTED_BY_REQUIRED",
        100,
    )
    reason = _required_string(payload, "reason", "REASON_REQUIRED", 500)
    evidence_reference = _optional_string(payload, "evidence_reference", 500)
    proposed_changes = _normalize_changes(
        payload.get("proposed_changes", {}),
        action,
        max_weight_kg,
    )
    if action == PesajeCorrectionRequest.ACTION_CORRECT and all(
        _original_value(pesaje, field) == value
        for field, value in proposed_changes.items()
    ):
        raise CorrectionValidationError(
            "NO_EFFECT",
            "Los valores propuestos coinciden con el pesaje original",
        )

    canonical = {
        "pesaje_id": pesaje.id,
        "action": action,
        "requested_by": requested_by,
        "reason": reason,
        "evidence_reference": evidence_reference,
        "proposed_changes": proposed_changes,
    }
    payload_hash = hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return canonical, payload_hash


class CorrectionRequestService:
    def create(self, request_id, pesaje, payload, max_weight_kg):
        normalized, payload_hash = normalize_correction_payload(
            pesaje,
            payload,
            max_weight_kg,
        )
        existing = PesajeCorrectionRequest.query.filter_by(
            request_id=request_id
        ).one_or_none()
        if existing is not None:
            return self._existing_result(existing, payload_hash)
        if pesaje.deleted_at is not None:
            raise PesajeAlreadyVoid(pesaje.id)

        source_classification = pesaje.traceability_classification
        status = (
            PesajeCorrectionRequest.REQUIRES_CENTRAL_REVIEW
            if source_classification == "LEGACY_ACKNOWLEDGED_UNVERIFIABLE"
            else PesajeCorrectionRequest.PENDING_LOCAL_REVIEW
        )
        request_record = PesajeCorrectionRequest(
            request_id=request_id,
            request_payload_hash=payload_hash,
            pesaje=pesaje,
            requested_by=normalized["requested_by"],
            action=normalized["action"],
            reason=normalized["reason"],
            evidence_reference=normalized["evidence_reference"],
            proposed_changes_json=json.dumps(
                normalized["proposed_changes"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            original_snapshot_json=json.dumps(
                snapshot_pesaje(pesaje),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            source_classification=source_classification,
            status=status,
        )
        db.session.add(request_record)
        try:
            db.session.commit()
            return CorrectionCreateResult(request=request_record, created=True)
        except IntegrityError:
            db.session.rollback()
            existing = PesajeCorrectionRequest.query.filter_by(
                request_id=request_id
            ).one_or_none()
            if existing is None:
                raise
            return self._existing_result(existing, payload_hash)

    @staticmethod
    def _existing_result(existing, payload_hash):
        if existing.request_payload_hash != payload_hash:
            raise CorrectionIdempotencyConflict(existing.request_id)
        return CorrectionCreateResult(request=existing, created=False)
