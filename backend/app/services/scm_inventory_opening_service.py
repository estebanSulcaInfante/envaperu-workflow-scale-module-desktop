"""Captura física conectada para la apertura inicial de inventario."""

import json
import uuid
from decimal import Decimal

from flask import current_app

from app.models.station_identity import StationIdentity
from app.routes.balanza import get_last_scale_snapshot
from app.runtime.token_store import read_configured_station_token
from app.services.central_api_client import CentralApiClient
from app.services.scm_weighing_service import ScmWeighingLocalError


def parse_opening_target(raw_value):
    try:
        payload = json.loads(str(raw_value or "").strip())
    except (json.JSONDecodeError, TypeError) as error:
        raise ScmWeighingLocalError(
            "INVALID_OPENING_TARGET_QR", "Escanea el QR de una jornada de apertura física."
        ) from error
    if payload.get("type") != "SCM_INVENTORY_OPENING_TARGET" or payload.get("v") != 1:
        raise ScmWeighingLocalError(
            "INVALID_OPENING_TARGET_QR", "El QR no corresponde a una apertura física SCM."
        )
    try:
        return {
            "opening_id": str(uuid.UUID(str(payload["opening_id"]))),
            "material_scm_id": int(payload["material_scm_id"]),
            "ubicacion_codigo": str(payload["ubicacion_codigo"]).strip().upper(),
            "estado_calidad": str(payload.get("estado_calidad") or "PENDIENTE").strip().upper(),
        }
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ScmWeighingLocalError(
            "INVALID_OPENING_TARGET_QR", "El QR de apertura está incompleto."
        ) from error


class ScmInventoryOpeningService:
    def __init__(self, *, client=None, scale_snapshot=None):
        self.client = client
        self.scale_snapshot = scale_snapshot

    @staticmethod
    def _station_id():
        identity = StationIdentity.query.one_or_none()
        value = identity.station_id if identity else current_app.config.get("STATION_UUID")
        if not value:
            raise ScmWeighingLocalError(
                "STATION_NOT_PROVISIONED", "La estación no posee identidad central.", status=503
            )
        return value

    @staticmethod
    def _operator_id():
        try:
            value = int(current_app.config.get("SCM_OPERATOR_ID"))
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            raise ScmWeighingLocalError(
                "SCM_OPERATOR_NOT_CONFIGURED", "Configura el operador de pesaje SCM.", status=503
            )
        return value

    @staticmethod
    def _client():
        configured = current_app.config.get("SCM_WEIGHING_CENTRAL_CLIENT")
        if configured is not None:
            return configured
        return CentralApiClient(
            origin=current_app.config["CENTRAL_ORIGIN"],
            token=read_configured_station_token(current_app._get_current_object()),
            station_version=current_app.config.get("STATION_APP_VERSION", "1.1.0-pilot"),
            allow_insecure=current_app.config.get("ALLOW_INSECURE_CENTRAL", False),
        )

    def capture(self, *, operation_id, target_qr, tara_kg):
        try:
            operation_id = str(uuid.UUID(str(operation_id)))
            tare = Decimal(str(tara_kg)).quantize(Decimal("0.001"))
        except (TypeError, ValueError, AttributeError) as error:
            raise ScmWeighingLocalError(
                "INVALID_CAPTURE", "La captura y la tara deben ser válidas."
            ) from error
        target = parse_opening_target(target_qr)
        snapshot = self.scale_snapshot() if self.scale_snapshot else get_last_scale_snapshot()
        if snapshot.get("peso_kg") is None or not snapshot.get("stable"):
            raise ScmWeighingLocalError(
                "SCALE_READING_UNSTABLE", "La captura requiere una lectura estable de balanza."
            )
        gross = Decimal(str(snapshot["peso_kg"])).quantize(Decimal("0.001"))
        if gross - tare <= 0:
            raise ScmWeighingLocalError("INVALID_NET_WEIGHT", "El peso NET debe ser mayor que cero.")
        payload = {
            **target,
            "peso_bruto_kg": format(gross, "f"),
            "tara_kg": format(tare, "f"),
            "pesado_por_id": self._operator_id(),
            "reading_stable": True,
        }
        client = self.client or self._client()
        opening = client.capture_inventory_opening_unit(
            self._station_id(), operation_id, payload
        )
        return {
            "opening": opening,
            "unidad": opening["unidades_logisticas"][-1],
        }

    def resolve(self, *, target_qr):
        target = parse_opening_target(target_qr)
        client = self.client or self._client()
        return client.resolve_inventory_opening_target(self._station_id(), target)


def get_scm_inventory_opening_service():
    configured = current_app.config.get("SCM_INVENTORY_OPENING_SERVICE")
    return configured or ScmInventoryOpeningService()
