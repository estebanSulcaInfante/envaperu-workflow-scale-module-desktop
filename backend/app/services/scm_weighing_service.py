"""Connected F2 coordinator. It never persists an offline SCM weighing."""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import current_app

from app.models.station_identity import StationIdentity
from app.routes.balanza import get_last_scale_snapshot
from app.runtime.token_store import read_configured_station_token
from app.services.central_api_client import CentralApiClient
from app.services.scm_prelabel_service import ScmPrelabelService


class ScmWeighingLocalError(RuntimeError):
    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def parse_scm_label_id(raw_value):
    value = str(raw_value or "").strip()
    if ";" in value:
        raise ScmWeighingLocalError(
            "LEGACY_QR_NOT_ACCEPTED",
            "El QR posicional legacy no identifica una manga SCM.",
        )
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        payload = {"label_id": value}
    if (
        payload.get("type") not in (None, "SCM_MANGA_LABEL")
        or payload.get("v") not in (None, 1)
    ):
        raise ScmWeighingLocalError(
            "INVALID_SCM_QR", "El QR no corresponde a una etiqueta SCM."
        )
    try:
        return str(uuid.UUID(str(payload.get("label_id"))))
    except (TypeError, ValueError, AttributeError) as error:
        raise ScmWeighingLocalError(
            "INVALID_SCM_QR", "El QR no contiene un label_id UUID valido."
        ) from error


class ScmWeighingService:
    def __init__(self, *, client=None, printer=None, scale_snapshot=None):
        self.client = client
        self.printer = printer
        self.scale_snapshot = scale_snapshot

    @staticmethod
    def _station_id():
        identity = StationIdentity.query.one_or_none()
        value = identity.station_id if identity else current_app.config.get(
            "STATION_UUID"
        )
        if not value:
            raise ScmWeighingLocalError(
                "STATION_NOT_PROVISIONED",
                "La estacion no posee identidad central.",
                status=503,
            )
        return value

    @staticmethod
    def _operator_id():
        raw = current_app.config.get("SCM_OPERATOR_ID")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = None
        if not value or value <= 0:
            raise ScmWeighingLocalError(
                "SCM_OPERATOR_NOT_CONFIGURED",
                "Configure el operador autenticado del piloto SCM.",
                status=503,
            )
        return value

    @staticmethod
    def _central_client():
        configured = current_app.config.get("SCM_WEIGHING_CENTRAL_CLIENT")
        if configured is not None:
            return configured
        return CentralApiClient(
            origin=current_app.config["CENTRAL_ORIGIN"],
            token=read_configured_station_token(
                current_app._get_current_object()
            ),
            station_version=current_app.config.get(
                "STATION_APP_VERSION", "1.1.0-pilot"
            ),
            allow_insecure=current_app.config.get(
                "ALLOW_INSECURE_CENTRAL", False
            ),
        )

    def resolve(self, qr_value):
        label_id = parse_scm_label_id(qr_value)
        if (
            current_app.config.get("ALLOW_LOCAL_SCM_DEMO")
            and label_id == "00000000-0000-4000-8000-000000000101"
        ):
            return {
                "can_weigh": True,
                "scanned_label_id": label_id,
                "demo_only": True,
                "manga": {
                    "codigo": "MNG-LOCAL-DEMO-001",
                    "op_ot": "OP-DEMO - OT-LOCAL-001",
                    "ot": {
                        "codigo": "OT-LOCAL-001",
                        "maquina": "Balanza simulada",
                        "turno": "DIA",
                    },
                    "trabajo_color": {
                        "codigo": "TC-LOCAL-001",
                        "estado": "EN_EJECUCION",
                        "orden_fabricacion": "OF-LOCAL-001",
                        "corrida": "OF-LOCAL-001-C01",
                        "color": "AZUL DEMO",
                    },
                    "asignacion_vigente": {
                        "maquinista": "Maquinista de prueba",
                    },
                    "fecha_operativa": "2026-08-13",
                    "maquinista": "Maquinista de prueba",
                    "pieza_color": "Pieza local de prueba",
                    "color": "AZUL DEMO",
                    "tipo": "NORMAL",
                    "cantidad_asignada_un": "100",
                    "tara_nominal_kg": "0.100",
                },
            }
        client = self.client or self._central_client()
        result = client.resolve_scm_manga_label(label_id)
        result["scanned_label_id"] = label_id
        return result

    def confirm(self, *, operation_id, label_id, motivo_desfase=None):
        try:
            operation_id = str(uuid.UUID(str(operation_id)))
            label_id = str(uuid.UUID(str(label_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise ScmWeighingLocalError(
                "INVALID_UUID", "La captura o etiqueta no posee UUID valido."
            ) from error
        client = self.client or self._central_client()
        context = client.resolve_scm_manga_label(label_id)
        if not context.get("can_weigh"):
            raise ScmWeighingLocalError(
                "MANGA_NOT_READY",
                "Central indica que la manga no esta lista para pesarse.",
                status=409,
            )
        snapshot = (
            self.scale_snapshot()
            if self.scale_snapshot is not None
            else get_last_scale_snapshot()
        )
        if snapshot.get("peso_kg") is None or not snapshot.get("stable"):
            raise ScmWeighingLocalError(
                "SCALE_READING_UNSTABLE",
                "F2 requiere una lectura NET estable de la balanza.",
            )
        gross = Decimal(str(snapshot["peso_kg"])).quantize(Decimal("0.001"))
        payload = {
            "label_id": label_id,
            "capture_id": operation_id,
            "peso_bruto_kg": format(gross, "f"),
            "tara_kg": context["manga"]["tara_nominal_kg"],
            "tara_fuente": "TIPO_MANGA",
            "pesada_at": datetime.now(timezone.utc).isoformat(),
            "pesado_por_id": self._operator_id(),
            "reading_stable": True,
            "motivo_desfase": (motivo_desfase or "").strip() or None,
        }
        confirmed = client.confirm_scm_manga_weighing(
            operation_id, payload
        )
        print_service = ScmPrelabelService(
            client=client,
            printer=self.printer,
        )
        print_result = print_service.print_job(
            confirmed["print_job_id"],
            operation_id=operation_id,
            capture_id=operation_id,
            manga_id=context["manga"].get("public_id"),
        )
        return {
            "operation_id": operation_id,
            "confirmed": confirmed,
            "print_result": print_result,
        }

    def recover(self, operation_id):
        try:
            canonical = str(uuid.UUID(str(operation_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise ScmWeighingLocalError(
                "INVALID_UUID", "operation_id no es un UUID valido."
            ) from error
        client = self.client or self._central_client()
        return client.get_scm_operation(canonical)


def get_scm_weighing_service():
    configured = current_app.config.get("SCM_WEIGHING_SERVICE")
    return configured or ScmWeighingService()
