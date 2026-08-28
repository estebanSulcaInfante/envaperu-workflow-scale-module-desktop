"""Fetch and print central PREPESAJE jobs without creating local weighings."""

import json
import hashlib
import base64
import io
import threading
from copy import deepcopy
from html import escape
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import qrcode
from qrcode.constants import ERROR_CORRECT_L
from flask import current_app, has_app_context

from app import db
from app.models.scm_label_print_attempt import ScmLabelPrintAttempt
from app.models.station_identity import StationIdentity
from app.runtime.token_store import read_configured_station_token
from app.services.central_api_client import CentralApiClient, CentralApiError
from app.services.printer_service import (
    PrinterEmissionResult,
    get_printer_service,
)


def _safe(value, limit=32):
    return str(value or "").replace('"', "'")[:limit]


def _tspl_quoted(value):
    """Escape embedded quotes using the sequence required by TSPL2."""
    return str(value or "").replace('"', r'\["]')


def _station_timezone(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "America/Lima":
            return timezone(timedelta(hours=-5), name)
        raise


class ScmPrelabelService:
    LEFT_X = 24
    RIGHT_X = 464
    STICKER_WIDTH = 400
    LABEL_HEIGHT_DOTS = 400
    TOP_BAR_Y = 14
    TEXT_START_Y = 18
    LINE_HEIGHT = 13
    QR_GAP_Y = 4
    QR_MODULE_DOTS = 4
    _physical_print_lock = threading.RLock()

    def __init__(self, *, client=None, printer=None):
        self.client = client
        self.printer = printer

    @staticmethod
    def _station_id():
        identity = StationIdentity.query.one_or_none()
        if identity is not None:
            return identity.station_id
        configured = current_app.config.get("STATION_UUID")
        if not configured:
            raise RuntimeError("La estacion no posee STATION_UUID")
        return configured

    @staticmethod
    def _central_client():
        configured = current_app.config.get("SCM_PRELABEL_CENTRAL_CLIENT")
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

    def fetch(self, print_job_id):
        client = self.client or self._central_client()
        job = client.get_scm_print_job(self._station_id(), print_job_id)
        return self._with_local_evidence(job)

    def list_jobs(self, *, status="PENDING", limit=20):
        client = self.client or self._central_client()
        response = client.list_scm_print_jobs(
            self._station_id(),
            status=status,
            limit=limit,
        )
        if not isinstance(response, dict):
            return response
        enriched = deepcopy(response)
        enriched["print_jobs"] = [
            self._with_local_evidence(job)
            for job in response.get("print_jobs", [])
        ]
        return enriched

    @staticmethod
    def _latest_attempts(print_job_id):
        if not has_app_context():
            return {}
        attempts = ScmLabelPrintAttempt.query.filter_by(
            print_job_id=print_job_id,
        ).order_by(ScmLabelPrintAttempt.id.desc()).all()
        latest = {}
        for attempt in attempts:
            latest.setdefault(attempt.label_id, attempt)
        return latest

    @staticmethod
    def _visible_state(state):
        if state == "EMISION_EN_PROGRESO":
            return "EMISION_INCIERTA"
        return state

    @classmethod
    def _aggregate_local_state(cls, latest):
        states = {
            cls._visible_state(attempt.result)
            for attempt in latest.values()
        }
        if not states:
            return None
        if "EMISION_INCIERTA" in states:
            return "EMISION_INCIERTA"
        if states == {"IMPRESA"}:
            return "IMPRESA"
        if states == {"FALLIDA_SIN_EMISION"}:
            return "FALLIDA_SIN_EMISION"
        return "PARCIAL"

    @classmethod
    def _with_local_evidence(cls, job, *, latest=None, ack_pending=None):
        if not isinstance(job, dict):
            return job
        enriched = deepcopy(job)
        print_job_id = enriched.get("print_job_id")
        latest = latest if latest is not None else cls._latest_attempts(
            print_job_id
        )
        for label in enriched.get("labels") or []:
            attempt = latest.get(str(label.get("public_id")))
            if attempt is not None:
                label["local_print_state"] = cls._visible_state(
                    attempt.result
                )
        local_state = cls._aggregate_local_state(latest)
        if local_state:
            enriched["local_print_state"] = local_state
        blocked = local_state in {"EMISION_INCIERTA", "PARCIAL"}
        if blocked:
            enriched["auto_reprint_blocked"] = True
        central_status = str(
            enriched.get("status") or enriched.get("estado") or ""
        ).upper()
        inferred_ack_pending = (
            local_state == "IMPRESA"
            and central_status not in {"PRINTED", "PROCESADO", "IMPRESA"}
        )
        if ack_pending is not None:
            inferred_ack_pending = bool(ack_pending)
        if local_state == "IMPRESA" or ack_pending is not None:
            enriched["ack_pending"] = inferred_ack_pending
        return enriched

    @staticmethod
    def _order_row(payload):
        if payload.get("of_ot"):
            return "OF/OT", payload["of_ot"]
        if payload.get("oa_ot"):
            return "OA/OT", payload["oa_ot"]
        return "OP/OT", payload.get("op_ot")

    @staticmethod
    def _qr_text(payload):
        return json.dumps(
            payload["qr"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _qr_code(cls, payload):
        qr = qrcode.QRCode(
            error_correction=ERROR_CORRECT_L,
            box_size=cls.QR_MODULE_DOTS,
            border=0,
        )
        qr.add_data(cls._qr_text(payload))
        qr.make(fit=True)
        return qr

    @classmethod
    def _rows(cls, payload, printed_at):
        order_label, order_ot = cls._order_row(payload)
        is_post_weighing = payload["qr"].get("label_type") == "POSTPESAJE"
        quantity_label = "CANT.REAL" if is_post_weighing else "CANT."
        quantity = (
            payload.get("cantidad_confirmada_un")
            if is_post_weighing else payload["cantidad_planificada_un"]
        ) or payload["cantidad_planificada_un"]
        rows = [
            ("MANGA", payload["codigo_manga"]),
            (order_label, order_ot),
            ("IMP.", printed_at),
            ("F.OT ORIG.", payload["fecha_ot"]),
            ("MAQ.ORIG.", payload["maquinista"]),
            ("PZA.", payload["pieza_color"]),
            ("COLOR", payload["color"]),
            ("TIPO", payload["tipo_manga"]),
            (quantity_label, quantity),
        ]
        if is_post_weighing:
            if payload.get("oa_ot"):
                rows.append(("NETO TOTAL ARM.", payload["kg_fisico"]))
            else:
                rows.extend((
                    ("KG FIS.", payload["kg_fisico"]),
                    ("KG OT", payload["kg_produccion_ot"]),
                ))
        return rows

    def _column(self, x, item, printed_at):
        payload = item["payload"]
        qr = self._qr_text(payload)
        y = self.TEXT_START_Y
        commands = [
            f"BAR {x},{self.TOP_BAR_Y},{self.STICKER_WIDTH},3"
        ]
        rows = self._rows(payload, printed_at)
        for label, value in rows:
            commands.append(
                f'TEXT {x + 5},{y},"1",0,1,1,'
                f'"{label}: {_safe(value)}"'
            )
            y += self.LINE_HEIGHT
        commands.append(f"BAR {x},{y},{self.STICKER_WIDTH},2")
        qr_y = y + self.QR_GAP_Y
        qr_size = self._qr_code(payload).modules_count * self.QR_MODULE_DOTS
        if qr_y + qr_size > self.LABEL_HEIGHT_DOTS:
            raise ValueError(
                "El QR SCM excede la altura fisica disponible de la etiqueta"
            )
        commands.append(
            f'QRCODE {x + 120},{qr_y},L,'
            f'{self.QR_MODULE_DOTS},A,0,M2,'
            f'"{_tspl_quoted(qr)}"'
        )
        return "\n".join(commands)

    @classmethod
    def _qr_data_uri(cls, payload):
        qr = cls._qr_code(payload)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return (
            "data:image/png;base64," + base64.b64encode(
                buffer.getvalue()
            ).decode("ascii"),
            qr.modules_count * cls.QR_MODULE_DOTS,
        )

    def _svg_column(self, x, item, printed_at):
        payload = item["payload"]
        rows = self._rows(payload, printed_at)
        y = self.TEXT_START_Y + 11
        parts = [
            f'<rect x="{x}" y="18" width="{self.STICKER_WIDTH}" '
            f'height="{self.LABEL_HEIGHT_DOTS - 18}" rx="4" '
            'fill="white" stroke="#111" stroke-width="2"/>',
        ]
        for label, value in rows:
            parts.append(
                f'<text x="{x + 7}" y="{y}" font-family="Arial, sans-serif" '
                f'font-size="13" font-weight="600">'
                f'{escape(f"{label}: {_safe(value)}")}</text>'
            )
            y += self.LINE_HEIGHT
        separator_y = self.TEXT_START_Y + len(rows) * self.LINE_HEIGHT
        qr_data_uri, qr_size = self._qr_data_uri(payload)
        parts.extend((
            f'<line x1="{x}" y1="{separator_y}" '
            f'x2="{x + self.STICKER_WIDTH}" y2="{separator_y}" '
            'stroke="#111" stroke-width="2"/>',
            f'<image href="{qr_data_uri}" x="{x + 120}" '
            f'y="{separator_y + self.QR_GAP_Y}" '
            f'width="{qr_size}" height="{qr_size}"/>',
        ))
        return "".join(parts)

    def generate_preview_svg(self, job, *, printed_at=None):
        """Render web-preview from the same coordinates as the TSPL."""
        labels = job.get("labels") or []
        if not 1 <= len(labels) <= 2:
            raise ValueError("El trabajo debe contener una o dos etiquetas")
        actual_printed_at = printed_at or datetime.now(timezone.utc)
        timezone_name = (
            current_app.config.get("TIMEZONE", "America/Lima")
            if has_app_context() else "America/Lima"
        )
        local_printed_at = actual_printed_at.astimezone(
            _station_timezone(timezone_name)
        ).strftime("%d/%m/%Y %H:%M")
        sheet_height = 400
        sheets = []
        for index, label in enumerate(labels):
            content = (
                '<rect width="872" height="400" fill="#e9edf2"/>'
                + self._svg_column(self.LEFT_X, label, local_printed_at)
                + self._svg_column(self.RIGHT_X, label, local_printed_at)
            )
            sheets.append(
                f'<g transform="translate(0,{index * sheet_height})">'
                f'{content}</g>'
            )
        total_height = sheet_height * len(labels)
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 872 {total_height}" width="109mm" '
            f'height="{50 * len(labels)}mm" '
            'role="img" aria-label="Vista previa física de etiquetas">'
            + "".join(sheets)
            + "</svg>"
        )

    def generate_tspl(self, job, *, printed_at=None):
        labels = job.get("labels") or []
        if not 1 <= len(labels) <= 2:
            raise ValueError("El trabajo debe contener una o dos etiquetas")
        actual_printed_at = printed_at or datetime.now(timezone.utc)
        timezone_name = (
            current_app.config.get("TIMEZONE", "America/Lima")
            if has_app_context() else "America/Lima"
        )
        local_printed_at = actual_printed_at.astimezone(
            _station_timezone(timezone_name)
        ).strftime("%d/%m/%Y %H:%M")
        pages = []
        for label in labels:
            pages.extend((
                "CLS",
                self._column(self.LEFT_X, label, local_printed_at),
                self._column(self.RIGHT_X, label, local_printed_at),
                "PRINT 1,1",
            ))
        return "\n".join((
            "SIZE 109 mm, 50 mm",
            "GAP 3 mm, 0 mm",
            "SET REFERENCE 0,0",
            "DIRECTION 1",
            "SET TEAR ON",
            "OFFSET 0 mm",
            "CODEPAGE UTF-8",
            *pages,
        )) + "\r\n"

    def print_job(
        self,
        print_job_id,
        *,
        operation_id=None,
        capture_id=None,
        manga_id=None,
    ):
        # La estación es de instancia única, y este lock evita dos requests
        # concurrentes que atraviesen el ledger antes de que alguna lo escriba.
        with self._physical_print_lock:
            return self._print_job_locked(
                print_job_id,
                operation_id=operation_id,
                capture_id=capture_id,
                manga_id=manga_id,
            )

    @staticmethod
    def _ack_results(latest):
        return [
            {
                "label_id": attempt.label_id,
                "estado": ScmPrelabelService._visible_state(attempt.result),
                "printer_name": attempt.printer_name,
                "error": attempt.error_detail,
            }
            for attempt in sorted(latest.values(), key=lambda item: item.id)
        ]

    def _acknowledge_local_result(
        self,
        *,
        client,
        print_job_id,
        latest,
        job,
        tspl=None,
        printer_emission=None,
        recovered=False,
    ):
        state = self._aggregate_local_state(latest)
        try:
            acknowledgement = client.acknowledge_scm_print_job(
                self._station_id(),
                print_job_id,
                {"results": self._ack_results(latest)},
            )
            ack_pending = False
            ack_error = None
        except CentralApiError as exc:
            # La emisión ya tiene evidencia durable. Un fallo de acuse no
            # modifica ese hecho y jamás debe provocar otra impresión.
            acknowledgement = None
            ack_pending = True
            ack_error = {"code": exc.state, "message": str(exc)}

        enriched_job = self._with_local_evidence(
            job,
            latest=latest,
            ack_pending=ack_pending,
        )
        blocked = state in {"EMISION_INCIERTA", "PARCIAL"}
        result = {
            "print_job": enriched_job,
            "tspl": tspl,
            "result": state,
            "central_ack": acknowledgement,
            "ack_pending": ack_pending,
            "ack_recovered": bool(recovered and not ack_pending),
            "auto_reprint_blocked": blocked,
        }
        if state == "IMPRESA" and recovered:
            result["already_printed"] = True
        if ack_error:
            result["central_ack_error"] = ack_error
        if printer_emission is not None:
            result["printer_emission"] = printer_emission.to_dict()
        return result

    @staticmethod
    def _local_job_snapshot(print_job_id, latest):
        return {
            "print_job_id": print_job_id,
            "labels": [
                {
                    "public_id": attempt.label_id,
                    "local_print_state": (
                        ScmPrelabelService._visible_state(attempt.result)
                    ),
                }
                for attempt in sorted(
                    latest.values(), key=lambda item: item.id
                )
            ],
        }

    def _resume_from_ledger(self, client, print_job_id):
        latest = self._latest_attempts(print_job_id)
        if not latest:
            return None

        incomplete = [
            attempt
            for attempt in latest.values()
            if attempt.result == "EMISION_EN_PROGRESO"
        ]
        if incomplete:
            completed = datetime.now(timezone.utc)
            for attempt in incomplete:
                attempt.result = "EMISION_INCIERTA"
                attempt.completed_at_utc = completed
                attempt.error_detail = (
                    "La estación se interrumpió entre el registro previo y "
                    "la confirmación del spooler; no reimprimir automáticamente"
                )
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise
            latest = self._latest_attempts(print_job_id)

        state = self._aggregate_local_state(latest)
        if state == "FALLIDA_SIN_EMISION":
            return None

        # IMPRESA, PARCIAL o EMISION_INCIERTA son terminales para el envío
        # físico. El endpoint se convierte exclusivamente en retry del acuse.
        return self._acknowledge_local_result(
            client=client,
            print_job_id=print_job_id,
            latest=latest,
            job=self._local_job_snapshot(print_job_id, latest),
            recovered=True,
        )

    @staticmethod
    def _emit(printer, tspl):
        detailed_print = getattr(printer, "print_tspl_result", None)
        if callable(detailed_print):
            try:
                result = detailed_print(tspl)
            except Exception as exc:
                return PrinterEmissionResult(
                    status=PrinterEmissionResult.UNCERTAIN,
                    expected_bytes=len(tspl.encode("utf-8")),
                    error=str(exc)[:500],
                )
            if isinstance(result, PrinterEmissionResult):
                return result
            status = getattr(result, "status", None)
            if status in {
                PrinterEmissionResult.ACCEPTED,
                PrinterEmissionResult.NOT_EMITTED,
                PrinterEmissionResult.UNCERTAIN,
            }:
                return PrinterEmissionResult(
                    status=status,
                    expected_bytes=getattr(
                        result, "expected_bytes", len(tspl.encode("utf-8"))
                    ),
                    bytes_written=getattr(result, "bytes_written", None),
                    document_started=bool(
                        getattr(result, "document_started", False)
                    ),
                    write_attempted=bool(
                        getattr(result, "write_attempted", False)
                    ),
                    simulated=bool(getattr(result, "simulated", False)),
                    job_id=getattr(result, "job_id", None),
                    error=getattr(result, "error", None),
                )
            return PrinterEmissionResult(
                status=PrinterEmissionResult.UNCERTAIN,
                expected_bytes=len(tspl.encode("utf-8")),
                error="La impresora devolvió un resultado no reconocido",
            )

        # Adaptador para impresoras de prueba/legacy. El PrinterService real
        # siempre expone el resultado detallado.
        try:
            success = bool(printer.print_tspl(tspl))
        except Exception as exc:
            return PrinterEmissionResult(
                status=PrinterEmissionResult.UNCERTAIN,
                expected_bytes=len(tspl.encode("utf-8")),
                error=str(exc)[:500],
            )
        return PrinterEmissionResult(
            status=(
                PrinterEmissionResult.ACCEPTED
                if success else PrinterEmissionResult.NOT_EMITTED
            ),
            expected_bytes=len(tspl.encode("utf-8")),
            error=None if success else "La impresora rechazó el trabajo",
        )

    def _print_job_locked(
        self,
        print_job_id,
        *,
        operation_id=None,
        capture_id=None,
        manga_id=None,
    ):
        client = self.client or self._central_client()
        resumed = self._resume_from_ledger(client, print_job_id)
        if resumed is not None:
            return resumed

        # Preview es read-only. La reserva ocurre inmediatamente antes del
        # pre-registro durable y de la interacción irreversible con el spooler.
        job = client.claim_scm_print_job(
            self._station_id(), print_job_id
        )
        attempted_at = datetime.now(timezone.utc)
        tspl = self.generate_tspl(job, printed_at=attempted_at)
        rendered_payload_hash = hashlib.sha256(
            tspl.encode("utf-8")
        ).hexdigest()
        printer = self.printer or current_app.config.get(
            "SCM_PRELABEL_PRINTER"
        ) or get_printer_service()
        printer_name = getattr(printer, "printer_name", None)

        attempts = []
        for label in job["labels"]:
            attempt = ScmLabelPrintAttempt(
                print_job_id=job["print_job_id"],
                label_id=label["public_id"],
                label_type=label["payload"]["qr"].get("label_type"),
                operation_id=operation_id,
                capture_id=capture_id,
                manga_id=(
                    manga_id
                    or label["payload"]["qr"].get("manga_id")
                ),
                payload_hash=label["payload_hash"],
                rendered_payload_hash=rendered_payload_hash,
                attempted_at_utc=attempted_at,
                completed_at_utc=None,
                printer_name=printer_name,
                result="EMISION_EN_PROGRESO",
                error_detail=None,
            )
            db.session.add(attempt)
            attempts.append(attempt)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        emission = self._emit(printer, tspl)
        state_by_emission = {
            PrinterEmissionResult.ACCEPTED: "IMPRESA",
            PrinterEmissionResult.NOT_EMITTED: "FALLIDA_SIN_EMISION",
            PrinterEmissionResult.UNCERTAIN: "EMISION_INCIERTA",
        }
        state = state_by_emission.get(
            emission.status, "EMISION_INCIERTA"
        )
        error = emission.error
        if state == "EMISION_INCIERTA" and not error:
            error = "El spooler no confirmó la emisión completa"
        completed = datetime.now(timezone.utc)
        actual_printer_name = getattr(printer, "printer_name", None)
        for attempt in attempts:
            attempt.completed_at_utc = completed
            attempt.printer_name = actual_printer_name
            attempt.result = state
            attempt.error_detail = error
        try:
            db.session.commit()
        except Exception:
            # EMISION_EN_PROGRESO ya es durable. Si este commit falla, un
            # próximo intento lo convertirá en incierto y no enviará otra copia.
            db.session.rollback()
            raise

        latest = self._latest_attempts(print_job_id)
        return self._acknowledge_local_result(
            client=client,
            print_job_id=print_job_id,
            latest=latest,
            job=job,
            tspl=tspl,
            printer_emission=emission,
        )


def get_scm_prelabel_service():
    configured = current_app.config.get("SCM_PRELABEL_SERVICE")
    return configured or ScmPrelabelService()
