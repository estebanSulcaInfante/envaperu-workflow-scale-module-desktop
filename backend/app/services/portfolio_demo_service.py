"""Safe, self-contained adapters for the public edge-station demo."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.routes.balanza import get_last_scale_snapshot
from app.services.scm_prelabel_service import ScmPrelabelService
from app.services.scm_weighing_service import (
    ScmWeighingLocalError,
    parse_scm_label_id,
)


DEMO_MANGA_ID = "00000000-0000-4000-8000-000000000201"
DEMO_PRELABEL_ID = "00000000-0000-4000-8000-000000000101"
DEMO_POSTLABEL_ID = "00000000-0000-4000-8000-000000000102"
DEMO_PREPRINT_JOB_ID = "00000000-0000-4000-8000-000000000301"
DEMO_POSTPRINT_JOB_ID = "00000000-0000-4000-8000-000000000302"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def demo_qr_text():
    return json.dumps(
        {
            "v": 1,
            "label_id": DEMO_PRELABEL_ID,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _label(*, label_id, label_type, gross=None, net=None):
    payload = {
        "codigo_manga": "OFDEMOAPPRE-OT001-M002",
        "of_ot": "OF-DEMO-AP-PRE - OT-000001",
        "fecha_ot": datetime.now(timezone.utc).date().isoformat(),
        "maquinista": "Diego Ramos",
        "operador": "Diego Ramos",
        "maquina": "Sopladora Alcancia Pablo",
        "turno": "DIA",
        "pieza": "Alcancia Pablo Grande",
        "pieza_color": "Alcancia Pablo Grande (PT-DEMO-AP)",
        "color": "CARNE SOLIDO",
        "tipo_manga": "NORMAL",
        "cantidad_planificada_un": "67",
        "kg_estimados": "8.950",
        "kg_teoricos": "8.950",
        "template": {
            "version": (
                "POSTPESAJE_TSPL_5"
                if label_type == "POSTPESAJE"
                else "PREPESAJE_TSPL_5"
            ),
            **(
                {"qr_contract": "LABEL_REF_V1"}
                if label_type == "PREPESAJE" else {}
            ),
        },
    }
    if label_type == "PREPESAJE":
        payload["qr"] = {
            "v": 1,
            "type": "SCM_MANGA_LABEL",
            "manga_id": DEMO_MANGA_ID,
            "label_id": label_id,
            "label_type": label_type,
            "label_version": 1,
        }
    else:
        payload.update(
            {
                "document_type": "POSTPESAJE",
                "manga_id": DEMO_MANGA_ID,
                "cantidad_confirmada_un": "67",
                "fuente_cantidad": "PLAN_CONFIRMADO_POR_PESAJE",
                "kg_fisico": format(net, "f"),
                "kg_produccion_ot": format(net, "f"),
                "peso_neto_real_kg": format(net, "f"),
                "peso_estandar_segun_unidades_kg": format(net, "f"),
                "peso_fabricado_teorico_kg": format(net, "f"),
                "aporte_desde_control_anterior_kg": format(net, "f"),
                "peso_bruto_kg": format(gross, "f"),
                "qr_required": False,
            }
        )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {
        "public_id": label_id,
        "payload_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "payload": payload,
    }


def demo_preprint_job():
    return {
        "print_job_id": DEMO_PREPRINT_JOB_ID,
        "status": "PENDING",
        "estado": "GENERADO",
        "created_at": _now_iso(),
        "processed_at": None,
        "plantilla_version": "PREPESAJE_TSPL_5",
        "labels": [
            _label(label_id=DEMO_PRELABEL_ID, label_type="PREPESAJE")
        ],
        "portfolio_demo": True,
    }


def demo_weighing_context():
    return {
        "can_weigh": True,
        "can_register_weight_control": True,
        "scanned_label_id": DEMO_PRELABEL_ID,
        "portfolio_demo": True,
        "manga": {
            "public_id": DEMO_MANGA_ID,
            "codigo": "OFDEMOAPPRE-OT001-M002",
            "op_ot": "OF-DEMO-AP-PRE - OT-000001",
            "ot": {
                "codigo": "OT-000001",
                "maquina": "Sopladora Alcancia Pablo",
                "turno": "DIA",
            },
            "trabajo_color": {
                "codigo": "OT-000001-TC01",
                "estado": "EN_EJECUCION",
                "orden_fabricacion": "OF-DEMO-AP-PRE",
                "corrida": "OF-DEMO-AP-PRE-C01",
                "color": "CARNE SOLIDO",
            },
            "asignacion_vigente": {"maquinista": "Diego Ramos"},
            "fecha_operativa": datetime.now(timezone.utc).date().isoformat(),
            "maquinista": "Diego Ramos",
            "pieza_color": "Alcancia Pablo Grande (PT-DEMO-AP)",
            "color": "CARNE SOLIDO",
            "tipo": "NORMAL",
            "cantidad_asignada_un": "67",
            "tara_nominal_kg": "0.100",
        },
    }


class PortfolioDemoPrelabelService(ScmPrelabelService):
    """Read and print a synthetic label without contacting central or hardware."""

    @staticmethod
    def _validate_job_id(print_job_id):
        if str(print_job_id) != DEMO_PREPRINT_JOB_ID:
            raise ValueError("Trabajo de impresion demo no encontrado")

    def list_jobs(self, *, status="PENDING", limit=20):
        items = [] if status not in {"PENDING", "ALL"} else [demo_preprint_job()]
        return {"print_jobs": items[:limit], "count": len(items[:limit])}

    def fetch(self, print_job_id):
        self._validate_job_id(print_job_id)
        return demo_preprint_job()

    def print_job(self, print_job_id, **_kwargs):
        self._validate_job_id(print_job_id)
        job = demo_preprint_job()
        job.update(
            {
                "status": "PRINTED",
                "estado": "PROCESADO",
                "processed_at": _now_iso(),
            }
        )
        return {
            "result": "IMPRESA",
            "simulated": True,
            "print_job": job,
            "preview_svg": self.generate_preview_svg(job),
        }


class PortfolioDemoWeighingService:
    """Idempotent in-memory weighing flow for the public portfolio surface."""

    def __init__(self, *, scale_snapshot=None):
        self.scale_snapshot = scale_snapshot or get_last_scale_snapshot
        self._operations = {}
        self._latest_control_net = Decimal("0.000")
        self._lock = threading.Lock()

    def resolve(self, qr_value):
        label_id = parse_scm_label_id(qr_value)
        if label_id != DEMO_PRELABEL_ID:
            raise ScmWeighingLocalError(
                "DEMO_LABEL_NOT_FOUND",
                "La demo publica solo admite la manga preparada.",
                status=404,
            )
        return demo_weighing_context()

    def confirm(
        self,
        *,
        operation_id,
        label_id,
        motivo_desfase=None,
        cantidad_confirmada_un=None,
        motivo_cierre_parcial=None,
    ):
        try:
            operation_id = str(uuid.UUID(str(operation_id)))
            label_id = str(uuid.UUID(str(label_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise ScmWeighingLocalError(
                "INVALID_UUID", "La operacion o etiqueta no posee UUID valido."
            ) from error
        if label_id != DEMO_PRELABEL_ID:
            raise ScmWeighingLocalError(
                "DEMO_LABEL_NOT_FOUND",
                "La demo publica solo admite la manga preparada.",
                status=404,
            )
        with self._lock:
            previous = self._operations.get(operation_id)
            if previous is not None:
                return copy.deepcopy(previous)

            snapshot = self.scale_snapshot()
            if snapshot.get("peso_kg") is None or not snapshot.get("stable"):
                raise ScmWeighingLocalError(
                    "SCALE_READING_UNSTABLE",
                    "Aplique una lectura estable de la balanza simulada.",
                )
            gross = Decimal(str(snapshot["peso_kg"])).quantize(Decimal("0.001"))
            tare = Decimal("0.100")
            net = (gross - tare).quantize(Decimal("0.001"))
            if net <= 0:
                raise ScmWeighingLocalError(
                    "INVALID_NET_WEIGHT", "El peso neto debe ser mayor que cero."
                )

            post_job = {
                "print_job_id": DEMO_POSTPRINT_JOB_ID,
                "status": "PRINTED",
                "estado": "PROCESADO",
                "created_at": _now_iso(),
                "processed_at": _now_iso(),
                "plantilla_version": "POSTPESAJE_TSPL_5",
                "labels": [
                    _label(
                        label_id=DEMO_POSTLABEL_ID,
                        label_type="POSTPESAJE",
                        gross=gross,
                        net=net,
                    )
                ],
                "portfolio_demo": True,
            }
            preview = ScmPrelabelService().generate_preview_svg(post_job)
            result = {
                "operation_id": operation_id,
                "portfolio_demo": True,
                "confirmed": {
                    "print_job_id": DEMO_POSTPRINT_JOB_ID,
                    "post_label": {"public_id": DEMO_POSTLABEL_ID},
                    "weighing": {
                        "public_id": operation_id,
                        "estado_manga": "PESADA",
                        "peso_bruto_kg": format(gross, "f"),
                        "tara_kg": format(tare, "f"),
                        "peso_fisico_neto_kg": format(net, "f"),
                        "kg_produccion_ot": format(net, "f"),
                        "motivo_desfase": (motivo_desfase or "").strip() or None,
                    },
                },
                "print_result": {
                    "result": "IMPRESA",
                    "simulated": True,
                    "preview_svg": preview,
                },
            }
            self._operations[operation_id] = copy.deepcopy(result)
            return result

    def record_control(self, *, operation_id, label_id):
        """Simulate the kg-only progress contract without closing the manga."""
        try:
            operation_id = str(uuid.UUID(str(operation_id)))
            label_id = str(uuid.UUID(str(label_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise ScmWeighingLocalError(
                "INVALID_UUID", "El control o la etiqueta no posee UUID valido."
            ) from error
        if label_id != DEMO_PRELABEL_ID:
            raise ScmWeighingLocalError(
                "DEMO_LABEL_NOT_FOUND",
                "La demo publica solo admite la manga preparada.",
                status=404,
            )
        with self._lock:
            previous = self._operations.get(operation_id)
            if previous is not None:
                return copy.deepcopy(previous)

            snapshot = self.scale_snapshot()
            if snapshot.get("peso_kg") is None or not snapshot.get("stable"):
                raise ScmWeighingLocalError(
                    "SCALE_READING_UNSTABLE",
                    "Aplique una lectura estable de la balanza simulada.",
                )
            gross = Decimal(str(snapshot["peso_kg"])).quantize(Decimal("0.001"))
            tare = Decimal("0.100")
            net = (gross - tare).quantize(Decimal("0.001"))
            if net <= self._latest_control_net:
                raise ScmWeighingLocalError(
                    "CONTROL_WEIGHT_NOT_MONOTONIC",
                    "El avance acumulado debe superar el ultimo control.",
                )
            contribution = (net - self._latest_control_net).quantize(
                Decimal("0.001")
            )
            control_label_id = str(
                uuid.uuid5(uuid.UUID(operation_id), "portfolio-control-label")
            )
            control_job_id = str(
                uuid.uuid5(uuid.UUID(operation_id), "portfolio-control-job")
            )
            payload = {
                "document_type": "CONTROL_PESO",
                "codigo_manga": "OFDEMOAPPRE-OT001-M002",
                "pieza_color": "Alcancia Pablo Grande (PT-DEMO-AP)",
                "maquinista": "Diego Ramos",
                "peso_neto_real_kg": format(net, "f"),
                "aporte_desde_control_anterior_kg": format(contribution, "f"),
                "qr_required": False,
                "template": {"version": "CONTROL_PESO_TSPL_2"},
            }
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            print_job = {
                "print_job_id": control_job_id,
                "status": "PRINTED",
                "estado": "PROCESADO",
                "created_at": _now_iso(),
                "processed_at": _now_iso(),
                "plantilla_version": "CONTROL_PESO_TSPL_2",
                "labels": [{
                    "public_id": control_label_id,
                    "payload_hash": hashlib.sha256(
                        canonical.encode("utf-8")
                    ).hexdigest(),
                    "payload": payload,
                }],
                "portfolio_demo": True,
            }
            preview = ScmPrelabelService().generate_preview_svg(print_job)
            result = {
                "operation_id": operation_id,
                "portfolio_demo": True,
                "continuidad_estado": "ACTIVA",
                "control": {
                    "tipo": "AVANCE_KG",
                    "peso_neto_kg": format(net, "f"),
                    "aporte_desde_control_anterior_kg": format(contribution, "f"),
                    "conteo_acumulado_un": None,
                },
                "manga": {
                    "public_id": DEMO_MANGA_ID,
                    "codigo": "OFDEMOAPPRE-OT001-M002",
                    "estado": "EN_LLENADO",
                },
                "print_job_id": control_job_id,
                "print_result": {
                    "result": "IMPRESA",
                    "simulated": True,
                    "preview_svg": preview,
                },
            }
            self._latest_control_net = net
            self._operations[operation_id] = copy.deepcopy(result)
            return result

    def recover(self, operation_id):
        try:
            canonical = str(uuid.UUID(str(operation_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise ScmWeighingLocalError(
                "INVALID_UUID", "operation_id no es un UUID valido."
            ) from error
        result = self._operations.get(canonical)
        if result is None:
            raise ScmWeighingLocalError(
                "DEMO_OPERATION_NOT_FOUND",
                "Operacion demo no encontrada.",
                status=404,
            )
        return copy.deepcopy(result)
