"""Pesaje conectado de aportes y bolsas de una OPM."""

import json
import uuid
from decimal import Decimal

from flask import current_app

from app.models.station_identity import StationIdentity
from app.routes.balanza import get_last_scale_snapshot
from app.runtime.token_store import read_configured_station_token
from app.services.central_api_client import CentralApiClient
from app.services.scm_weighing_service import ScmWeighingLocalError


def parse_preparation_target(raw_value):
    try:
        payload = json.loads(str(raw_value or "").strip())
    except (json.JSONDecodeError, TypeError) as error:
        raise ScmWeighingLocalError(
            "INVALID_PREPARATION_TARGET_QR", "Escanea el contexto QR de la OPM."
        ) from error
    if payload.get("type") != "SCM_PREPARATION_WEIGHT_TARGET" or payload.get("v") != 1:
        raise ScmWeighingLocalError(
            "INVALID_PREPARATION_TARGET_QR", "El QR no corresponde a un pesaje OPM."
        )
    return payload


class ScmPreparedMaterialWeighingService:
    def __init__(self, *, client=None, scale_snapshot=None):
        self.client = client
        self.scale_snapshot = scale_snapshot

    @staticmethod
    def _station_id():
        identity = StationIdentity.query.one_or_none()
        value = identity.station_id if identity else current_app.config.get("STATION_UUID")
        if not value:
            raise ScmWeighingLocalError("STATION_NOT_PROVISIONED", "Estación sin identidad.", status=503)
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
            raise ScmWeighingLocalError("INVALID_CAPTURE", "Captura o tara inválida.") from error
        target = parse_preparation_target(target_qr)
        snapshot = self.scale_snapshot() if self.scale_snapshot else get_last_scale_snapshot()
        if snapshot.get("peso_kg") is None or not snapshot.get("stable"):
            raise ScmWeighingLocalError("SCALE_READING_UNSTABLE", "La lectura de balanza no está estable.")
        gross = Decimal(str(snapshot["peso_kg"])).quantize(Decimal("0.001"))
        net = gross - tare
        if net <= 0:
            raise ScmWeighingLocalError("INVALID_NET_WEIGHT", "El peso NET debe ser mayor que cero.")
        payload = {
            "orden_preparacion_id": target.get("orden_preparacion_id"),
            "version": target.get("version"),
            "tipo_uso": target.get("tipo_uso"),
            "asignacion_requerimiento_id": target.get("asignacion_requerimiento_id"),
            "pesado_por_id": target.get("pesado_por_id"),
            "peso_bruto_kg": format(gross, "f"),
            "tara_kg": format(tare, "f"),
            "peso_neto_kg": format(net, "f"),
            "reading_stable": True,
            "unidades_origen_qr": target.get("unidades_origen_qr") or [],
        }
        return self._client().capture_prepared_material_reading(
            self._station_id(), operation_id, payload
        )

    def resolve_source(self, *, target_qr, source_qr):
        target = parse_preparation_target(target_qr)
        if target.get("tipo_uso") != "APORTE":
            raise ScmWeighingLocalError(
                "INVALID_PREPARATION_SOURCE_CONTEXT",
                "Las bolsas origen solo se escanean durante un aporte.",
            )
        qr = str(source_qr or "").strip()
        if not qr.startswith("SCM:UL:"):
            raise ScmWeighingLocalError(
                "INVALID_SOURCE_UNIT_QR", "Escanea el sticker SCM:UL de una bolsa origen."
            )
        return self._client().resolve_prepared_material_source_unit(
            self._station_id(),
            {
                "orden_preparacion_id": target.get("orden_preparacion_id"),
                "actor_id": target.get("pesado_por_id"),
                "qr_value": qr,
            },
        )


def get_scm_prepared_material_weighing_service():
    configured = current_app.config.get("SCM_PREPARED_MATERIAL_WEIGHING_SERVICE")
    return configured or ScmPreparedMaterialWeighingService()
