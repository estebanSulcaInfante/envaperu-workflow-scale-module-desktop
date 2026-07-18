import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from jsonschema import Draft202012Validator, FormatChecker

from app import db
from app.models.pesaje import Pesaje
from app.models.station_identity import StationIdentity, StationRuntimeState
from app.runtime.token_store import read_configured_station_token
from app.services.central_api_client import CentralApiClient, CentralApiError
from app.services.legacy_continuity_service import (
    apply_pilot_command,
    build_history_delta,
)


def _utc_now():
    return datetime.now(timezone.utc)


def _ensure_utc(value, local_zone=None):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=local_zone or timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_utc(value, local_zone=None):
    value = _ensure_utc(value, local_zone=local_zone)
    return value.isoformat() if value else None


def _parse_utc(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _ensure_utc(parsed)


def _operational_timezone(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "America/Lima":
            return timezone(timedelta(hours=-5), name="America/Lima")
        raise


def _progress_dimension(value):
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split()).upper()
    return normalized or None


@lru_cache(maxsize=4)
def _contract_validator(contract_name, definition):
    path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / contract_name
        / "contract.schema.json"
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema["$defs"][definition],
        format_checker=FormatChecker(),
    )


def _validate_contract(contract_name, definition, payload, error_state):
    errors = sorted(
        _contract_validator(contract_name, definition).iter_errors(payload),
        key=lambda item: list(item.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path) or "payload"
    raise CentralApiError(
        error_state,
        f"{contract_name}.{definition} invalido en {location}: {error.message}",
    )


def initialize_station_monitoring(app):
    station_code = str(
        app.config.get("STATION_ID")
        or app.config.get("STATION_CODE")
        or "PESAJE-PLANTA-01"
    ).strip()
    identity = StationIdentity.query.one_or_none()
    if identity is None:
        configured_id = app.config.get("STATION_UUID")
        station_id = str(uuid.UUID(configured_id)) if configured_id else str(uuid.uuid4())
        identity = StationIdentity(
            station_id=station_id,
            station_code=station_code,
            created_at_utc=_utc_now(),
        )
        db.session.add(identity)
    elif identity.station_code != station_code:
        raise RuntimeError(
            "STATION_CODE no coincide con la identidad persistida: "
            f"{identity.station_code}"
        )

    runtime = db.session.get(StationRuntimeState, identity.station_id)
    if runtime is None:
        runtime = StationRuntimeState(
            station_id=identity.station_id,
            communication_state="CENTRAL_NOT_PROVISIONED",
        )
        db.session.add(runtime)
    runtime.boot_id = str(uuid.uuid4())
    runtime.sequence = 0
    runtime.started_at_utc = _utc_now()
    runtime.last_attempt_at_utc = None
    runtime.last_heartbeat_id = None
    runtime.next_heartbeat_seconds = int(
        app.config.get("HEARTBEAT_SECONDS", 30)
    )
    db.session.commit()
    app.config["STATION_UUID"] = identity.station_id
    app.config["STATION_BOOT_ID"] = runtime.boot_id
    return identity, runtime


def _default_component_provider():
    from app.runtime.lifecycle import RuntimeState
    from app.services.printer_service import get_printer_service
    from app.services.scale_service import get_scale_service

    runtime = current_app.config.get("RUNTIME_STATE")
    process_state = runtime.status if runtime is not None else RuntimeState.READY
    try:
        db.session.execute(db.text("SELECT 1"))
        database_state = "READY"
    except Exception:
        db.session.rollback()
        database_state = "ERROR"

    scale_status = get_scale_service().get_status()
    if scale_status.get("connected") and scale_status.get("listening"):
        scale_state = "CONNECTED_LISTENING"
    elif scale_status.get("connected"):
        scale_state = "CONNECTED_IDLE"
    else:
        scale_state = "DISCONNECTED"

    printer_status = get_printer_service().get_status()
    printer_state = (
        "AVAILABLE"
        if printer_status.get("connected")
        else "NO_VERIFICADO"
    )
    return {
        "process": process_state,
        "database": database_state,
        "scale": scale_state,
        "printer": printer_state,
        "catalog": "LEGACY_CACHE",
    }


class MonitoringService:
    def __init__(
        self,
        *,
        client_factory=None,
        token_provider=None,
        component_provider=None,
        now=None,
        monotonic=None,
    ):
        self.token_provider = token_provider or (
            lambda: read_configured_station_token(current_app._get_current_object())
        )
        self.client_factory = client_factory or self._create_client
        self.component_provider = component_provider or _default_component_provider
        self.now = now or _utc_now
        self.monotonic = monotonic or time.monotonic
        self._started_monotonic = self.monotonic()
        self._capabilities_verified = False

    @staticmethod
    def _create_client(token):
        return CentralApiClient(
            origin=current_app.config["CENTRAL_ORIGIN"],
            token=token,
            station_version=current_app.config.get(
                "STATION_APP_VERSION",
                "1.1.0-pilot",
            ),
            allow_insecure=current_app.config.get(
                "ALLOW_INSECURE_CENTRAL",
                False,
            ),
        )

    @staticmethod
    def _identity_and_runtime():
        identity = StationIdentity.query.one()
        runtime = db.session.get(StationRuntimeState, identity.station_id)
        if runtime is None:
            raise RuntimeError("StationRuntimeState no inicializado")
        return identity, runtime

    @staticmethod
    def _validate_capabilities(payload):
        _validate_contract(
            "station-capabilities-v1",
            "response",
            payload,
            "CENTRAL_INCOMPATIBLE",
        )
        if payload["features"]["monitoring"] is not True:
            raise CentralApiError(
                "CENTRAL_INCOMPATIBLE",
                "Central no habilita monitoreo",
            )
        if (
            "station-production-progress-v1"
            not in payload["supported_contracts"]["weight_event"]
        ):
            raise CentralApiError(
                "CENTRAL_INCOMPATIBLE",
                "Central no soporta station-production-progress-v1",
            )
        if (
            "station-legacy-continuity-v1"
            not in payload["supported_contracts"]["weight_event"]
            or payload["features"].get("pilot_data_commands") is not True
        ):
            raise CentralApiError(
                "CENTRAL_INCOMPATIBLE",
                "Central no soporta continuidad operativa del piloto",
            )

    @staticmethod
    def _sync_continuity(client, station_id):
        state = client.get_history_sync_state(station_id)
        delta = build_history_delta(station_id, state["high_watermark"])
        delta_ack = client.send_history_delta(station_id, delta)
        if (
            delta_ack.get("accepted") is not True
            or delta_ack.get("batch_id") != delta["batch_id"]
        ):
            raise CentralApiError(
                "CONTRACT_CONFLICT",
                "Acuse central no coincide con el delta legacy",
            )

        commands = client.get_pilot_commands(station_id).get("items", [])
        for command in commands:
            try:
                result = apply_pilot_command(command)
                ack_payload = {"status": "APPLIED", "result": result}
            except Exception as exc:
                db.session.rollback()
                ack_payload = {
                    "status": "FAILED",
                    "error_code": str(exc)[:100] or type(exc).__name__,
                    "result": {},
                }
            client.acknowledge_pilot_command(
                station_id,
                command["command_id"],
                ack_payload,
            )
        return delta_ack

    def _legacy_snapshot(self, now):
        timezone_name = current_app.config.get("TIMEZONE", "America/Lima")
        local_zone = _operational_timezone(timezone_name)
        local_now = _ensure_utc(now).astimezone(local_zone)
        window_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_end = local_now
        naive_start = window_start.replace(tzinfo=None)
        naive_end = window_end.replace(tzinfo=None)

        active = Pesaje.active()
        pending = active.filter_by(sincronizado=False)
        pending_count = pending.count()
        oldest = pending.order_by(Pesaje.fecha_hora.asc()).first()
        day_rows = active.filter(
            Pesaje.fecha_hora >= naive_start,
            Pesaje.fecha_hora <= naive_end,
        ).all()
        total = sum(
            (Decimal(str(row.peso_kg or 0)) for row in day_rows),
            Decimal("0"),
        ).quantize(Decimal("0.001"))
        latest = active.order_by(Pesaje.fecha_hora.desc(), Pesaje.id.desc()).first()

        last_capture = None
        context = {"op": None, "ot": None, "machine_code": None, "shift": None}
        if latest is not None:
            context = {
                "op": latest.nro_op,
                "ot": latest.nro_orden_trabajo,
                "machine_code": latest.maquina,
                "shift": latest.turno,
            }
            print_state = {
                "SAVED_PRINTED": "PRINTED",
                "SAVED_PRINT_FAILED": "FAILED",
            }.get(latest.print_status, "PENDING")
            last_capture = {
                "capture_id": latest.capture_id,
                "captured_at_utc": _iso_utc(
                    latest.fecha_hora,
                    local_zone=local_zone,
                ),
                "weight_kg": format(
                    Decimal(str(latest.peso_kg)).quantize(Decimal("0.001")),
                    "f",
                ),
                "print_state": print_state,
            }

        return {
            "pending_count": pending_count,
            "oldest_pending_at_utc": (
                _iso_utc(oldest.fecha_hora, local_zone=local_zone)
                if oldest
                else None
            ),
            "context": context,
            "last_capture": last_capture,
            "summary": {
                "source": "LOCAL_REPORTED_LEGACY",
                "timezone": timezone_name,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "bags": len(day_rows),
                "weight_kg": format(total, "f"),
            },
        }

    def _build_production_progress_payload(self, now):
        timezone_name = current_app.config.get("TIMEZONE", "America/Lima")
        if timezone_name != "America/Lima":
            raise CentralApiError(
                "CONTRACT_CONFLICT",
                "station-production-progress-v1 requiere America/Lima",
            )
        local_zone = _operational_timezone(timezone_name)
        local_now = _ensure_utc(now).astimezone(local_zone)
        window_days = int(current_app.config.get("PRODUCTION_PROGRESS_DAYS", 31))
        if not 1 <= window_days <= 31:
            raise CentralApiError(
                "CONTRACT_CONFLICT",
                "PRODUCTION_PROGRESS_DAYS debe estar entre 1 y 31",
            )
        window_end_date = local_now.date()
        window_start_date = window_end_date - timedelta(days=window_days - 1)
        window_start = local_now.replace(
            year=window_start_date.year,
            month=window_start_date.month,
            day=window_start_date.day,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        window_end_exclusive = local_now.replace(
            year=window_end_date.year,
            month=window_end_date.month,
            day=window_end_date.day,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ) + timedelta(days=1)
        naive_start = window_start.replace(tzinfo=None)
        naive_end = window_end_exclusive.replace(tzinfo=None)

        all_rows = Pesaje.query.filter(
            Pesaje.fecha_hora >= naive_start,
            Pesaje.fecha_hora < naive_end,
        ).all()
        active_rows = [row for row in all_rows if row.deleted_at is None]
        groups = {}
        revision_markers = []

        for row in all_rows:
            revision_markers.append(
                _ensure_utc(row.fecha_hora, local_zone=local_zone)
            )
            if row.deleted_at is not None:
                revision_markers.append(
                    _ensure_utc(row.deleted_at, local_zone=local_zone)
                )

        for row in active_rows:
            weight = Decimal(str(row.peso_kg or 0)).quantize(Decimal("0.001"))
            if weight <= 0:
                raise CentralApiError(
                    "CONTRACT_CONFLICT",
                    f"Pesaje local {row.id} tiene peso no positivo",
                )
            captured_at = _ensure_utc(row.fecha_hora, local_zone=local_zone)
            operational_date = captured_at.astimezone(local_zone).date().isoformat()
            dimensions = (
                _progress_dimension(row.nro_op),
                _progress_dimension(row.nro_orden_trabajo),
                _progress_dimension(row.molde),
                _progress_dimension(row.color),
                _progress_dimension(row.maquina),
                _progress_dimension(row.turno),
            )
            key = (operational_date, *dimensions)
            bucket = groups.setdefault(
                key,
                {
                    "bags": 0,
                    "weight_kg": Decimal("0"),
                    "first_capture_at_utc": captured_at,
                    "last_capture_at_utc": captured_at,
                },
            )
            bucket["bags"] += 1
            bucket["weight_kg"] += weight
            bucket["first_capture_at_utc"] = min(
                bucket["first_capture_at_utc"],
                captured_at,
            )
            bucket["last_capture_at_utc"] = max(
                bucket["last_capture_at_utc"],
                captured_at,
            )

        rows = []
        for key in sorted(groups, key=lambda value: tuple(part or "" for part in value)):
            operational_date, op, ot, mold, color, machine_code, shift = key
            bucket = groups[key]
            rows.append(
                {
                    "operational_date": operational_date,
                    "op": op,
                    "ot": ot,
                    "mold": mold,
                    "color": color,
                    "machine_code": machine_code,
                    "shift": shift,
                    "bags": bucket["bags"],
                    "weight_kg": format(
                        bucket["weight_kg"].quantize(Decimal("0.001")),
                        "f",
                    ),
                    "first_capture_at_utc": _iso_utc(
                        bucket["first_capture_at_utc"]
                    ),
                    "last_capture_at_utc": _iso_utc(
                        bucket["last_capture_at_utc"]
                    ),
                }
            )

        generated_at = (
            max(revision_markers)
            if revision_markers
            else window_end_exclusive - timedelta(days=1)
        )
        base_payload = {
            "contract_version": "station-production-progress-v1",
            "generated_at_utc": _iso_utc(generated_at),
            "timezone": timezone_name,
            "window_start_date": window_start_date.isoformat(),
            "window_end_date": window_end_date.isoformat(),
            "source": "LOCAL_REPORTED_LEGACY",
            "rows": rows,
        }
        identity = StationIdentity.query.one()
        canonical = json.dumps(
            base_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return {
            **base_payload,
            "report_id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"envaperu:{identity.station_id}:production-progress:{digest}",
                )
            ),
        }

    def _build_payload(self, identity, runtime, now):
        snapshot = self._legacy_snapshot(now)
        return {
            "contract_version": "station-heartbeat-v1",
            "heartbeat_id": str(uuid.uuid4()),
            "boot_id": runtime.boot_id,
            "sequence": runtime.sequence,
            "generated_at_utc": _iso_utc(now),
            "app_version": current_app.config.get(
                "STATION_APP_VERSION",
                "1.1.0-pilot",
            ),
            "mode": current_app.config.get(
                "STATION_MODE",
                "MONITORED_LEGACY",
            ),
            "uptime_seconds": max(
                0,
                int(self.monotonic() - self._started_monotonic),
            ),
            "components": self.component_provider(),
            "communication": {
                "last_central_ack_utc": _iso_utc(
                    runtime.last_central_ack_utc
                ),
                "state": runtime.communication_state,
                "legacy_unsynced_count": snapshot["pending_count"],
                "oldest_legacy_unsynced_at_utc": snapshot[
                    "oldest_pending_at_utc"
                ],
                "last_error_code": runtime.last_error_code,
            },
            "context": snapshot["context"],
            "last_capture": snapshot["last_capture"],
            "local_summary": snapshot["summary"],
        }

    def _record_failure(self, runtime, state, now):
        runtime.communication_state = state
        runtime.last_error_code = state
        runtime.last_attempt_at_utc = now
        db.session.commit()
        return runtime.to_monitoring_dict()

    def run_once(self):
        identity, runtime = self._identity_and_runtime()
        now = _ensure_utc(self.now())
        try:
            token = self.token_provider()
        except Exception:
            return self._record_failure(
                runtime,
                "CENTRAL_NOT_PROVISIONED",
                now,
            )
        if not token:
            return self._record_failure(
                runtime,
                "CENTRAL_NOT_PROVISIONED",
                now,
            )

        try:
            client = self.client_factory(token)
            if not self._capabilities_verified:
                self._validate_capabilities(client.get_capabilities())
                self._capabilities_verified = True

            runtime.sequence += 1
            runtime.last_attempt_at_utc = now
            db.session.commit()
            payload = self._build_payload(identity, runtime, now)
            _validate_contract(
                "station-heartbeat-v1",
                "request",
                payload,
                "CONTRACT_CONFLICT",
            )
            ack = client.send_heartbeat(identity.station_id, payload)
            _validate_contract(
                "station-heartbeat-v1",
                "response",
                ack,
                "CENTRAL_INCOMPATIBLE",
            )
            if (
                ack.get("accepted") is not True
                or ack.get("station_id") != identity.station_id
                or ack.get("heartbeat_id") != payload["heartbeat_id"]
            ):
                raise CentralApiError(
                    "CONTRACT_CONFLICT",
                    "Acuse central no coincide con el heartbeat",
                )
            self._sync_continuity(client, identity.station_id)
            progress_payload = self._build_production_progress_payload(now)
            _validate_contract(
                "station-production-progress-v1",
                "request",
                progress_payload,
                "CONTRACT_CONFLICT",
            )
            progress_ack = client.send_production_progress(
                identity.station_id,
                progress_payload,
            )
            _validate_contract(
                "station-production-progress-v1",
                "response",
                progress_ack,
                "CENTRAL_INCOMPATIBLE",
            )
            if (
                progress_ack.get("accepted") is not True
                or progress_ack.get("station_id") != identity.station_id
                or progress_ack.get("report_id") != progress_payload["report_id"]
            ):
                raise CentralApiError(
                    "CONTRACT_CONFLICT",
                    "Acuse central no coincide con el reporte de avance",
                )
        except ValueError:
            return self._record_failure(
                runtime,
                "CENTRAL_CONFIG_ERROR",
                now,
            )
        except CentralApiError as exc:
            return self._record_failure(runtime, exc.state, now)

        runtime.communication_state = "ONLINE"
        runtime.last_error_code = None
        runtime.last_central_ack_utc = _parse_utc(
            progress_ack["received_at_utc"]
        )
        runtime.last_heartbeat_id = payload["heartbeat_id"]
        runtime.next_heartbeat_seconds = int(
            ack.get(
                "next_heartbeat_seconds",
                current_app.config.get("HEARTBEAT_SECONDS", 30),
            )
        )
        db.session.commit()
        return runtime.to_monitoring_dict()
