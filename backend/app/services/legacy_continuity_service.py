import hashlib
import json
import uuid
from decimal import Decimal

from app import db
from app.models.op_cerrada import OpCerrada
from app.models.pesaje import Pesaje


BATCH_NAMESPACE = uuid.UUID("da87d32d-f5cc-407d-abf1-a0ff92f354ae")


def _local_text(value):
    if value is None:
        return None
    return value.isoformat(sep=" ")


def _row(pesaje):
    return {
        "legacy_id": pesaje.id,
        "weight_kg": format(Decimal(str(pesaje.peso_kg)).quantize(Decimal("0.001")), "f"),
        "captured_at_local": _local_text(pesaje.fecha_hora),
        "deleted_at_local": _local_text(pesaje.deleted_at),
        "op": pesaje.nro_op,
        "ot": pesaje.nro_orden_trabajo,
        "mold": pesaje.molde,
        "color": pesaje.color,
        "machine_code": pesaje.maquina,
        "shift": pesaje.turno,
        "operator": pesaje.operador,
        "raw": {
            "id": pesaje.id,
            "capture_id": pesaje.capture_id,
            "peso_bruto_kg": pesaje.peso_bruto_kg,
            "fraccion_descuento": pesaje.fraccion_descuento,
            "pieza_sku": pesaje.pieza_sku,
            "pieza_nombre": pesaje.pieza_nombre,
            "observaciones": pesaje.observaciones,
        },
    }


def _closure(item):
    return {
        "op": item.nro_op,
        "mold": item.molde,
        "reason": item.motivo,
        "closed_at_local": _local_text(item.fecha_cierre),
    }


def build_history_delta(station_id, high_watermark, *, limit=500):
    rows = (
        Pesaje.query.filter(Pesaje.id > int(high_watermark))
        .order_by(Pesaje.id)
        .limit(limit)
        .all()
    )
    closures = OpCerrada.query.order_by(OpCerrada.nro_op).all()
    base = {
        "contract_version": "station-legacy-continuity-v1",
        "rows": [_row(item) for item in rows],
        "closures": [_closure(item) for item in closures],
    }
    digest = hashlib.sha256(
        json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        **base,
        "batch_id": str(
            uuid.uuid5(
                BATCH_NAMESPACE,
                f"{station_id}:{int(high_watermark)}:{digest}",
            )
        ),
    }


def apply_pilot_command(command):
    action = command.get("action")
    if action == "VOID_CAPTURE":
        pesaje = db.session.get(Pesaje, command.get("legacy_pesaje_id"))
        if pesaje is None:
            raise LookupError("CAPTURE_NOT_FOUND")
        if pesaje.deleted_at is None:
            pesaje.soft_delete()
            db.session.commit()
        return {"deleted_at_local": _local_text(pesaje.deleted_at)}

    op_raw = str(command.get("op") or "").strip()
    if not op_raw:
        raise ValueError("OP_REQUIRED")
    closure = OpCerrada.query.filter_by(nro_op=op_raw).one_or_none()
    if action == "REOPEN_OP":
        if closure is not None:
            db.session.delete(closure)
            db.session.commit()
        return {}
    if action != "CLOSE_OP":
        raise ValueError("ACTION_NOT_SUPPORTED")
    if closure is None:
        pesaje = (
            Pesaje.active()
            .filter_by(nro_op=op_raw)
            .order_by(Pesaje.fecha_hora.desc())
            .first()
        )
        closure = OpCerrada(
            nro_op=op_raw,
            molde=pesaje.molde if pesaje else None,
            motivo=command.get("reason"),
        )
        db.session.add(closure)
        db.session.commit()
    return {
        "closed_at_local": _local_text(closure.fecha_cierre),
        "mold": closure.molde,
    }
