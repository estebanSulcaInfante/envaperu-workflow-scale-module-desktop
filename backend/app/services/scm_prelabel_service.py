"""Fetch and print central PREPESAJE jobs without creating local weighings."""

import json
import hashlib
import base64
import io
from html import escape
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import qrcode
from flask import current_app, has_app_context

from app import db
from app.models.scm_label_print_attempt import ScmLabelPrintAttempt
from app.models.station_identity import StationIdentity
from app.runtime.token_store import read_configured_station_token
from app.services.central_api_client import CentralApiClient
from app.services.printer_service import get_printer_service


def _safe(value, limit=32):
    return str(value or "").replace('"', "'")[:limit]


def _tspl_quoted(value, limit=600):
    return (
        str(value or "")[:limit]
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )


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
    LINE_HEIGHT = 22

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
        return client.get_scm_print_job(self._station_id(), print_job_id)

    def list_jobs(self, *, status="PENDING", limit=20):
        client = self.client or self._central_client()
        return client.list_scm_print_jobs(
            self._station_id(),
            status=status,
            limit=limit,
        )

    @staticmethod
    def _order_row(payload):
        if payload.get("of_ot"):
            return "OF/OT", payload["of_ot"]
        if payload.get("oa_ot"):
            return "OA/OT", payload["oa_ot"]
        return "OP/OT", payload.get("op_ot")

    def _column(self, x, item, printed_at):
        payload = item["payload"]
        order_label, order_ot = self._order_row(payload)
        qr = json.dumps(
            payload["qr"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        y = 22
        commands = [f"BAR {x},18,{self.STICKER_WIDTH},3"]
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
            rows.extend((
                ("KG FIS.", payload["kg_fisico"]),
                ("KG OT", payload["kg_produccion_ot"]),
            ))
        for label, value in rows:
            commands.append(
                f'TEXT {x + 5},{y},"1",0,1,1,'
                f'"{label}: {_safe(value)}"'
            )
            y += self.LINE_HEIGHT
        commands.append(f"BAR {x},{y},{self.STICKER_WIDTH},2")
        commands.append(
            f'QRCODE {x + 120},{y + 10},L,4,A,0,'
            f'"{_tspl_quoted(qr)}"'
        )
        return "\n".join(commands)

    @staticmethod
    def _qr_data_uri(payload):
        qr_text = json.dumps(
            payload["qr"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        image = qrcode.make(qr_text)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(
            buffer.getvalue()
        ).decode("ascii")

    def _svg_column(self, x, item, printed_at):
        payload = item["payload"]
        order_label, order_ot = self._order_row(payload)
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
            rows.extend((
                ("KG FIS.", payload["kg_fisico"]),
                ("KG OT", payload["kg_produccion_ot"]),
            ))
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
            f'<image href="{self._qr_data_uri(payload)}" '
            f'x="{x + 120}" y="{y + 8}" width="120" height="120"/>',
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
            *pages,
        ))

    def print_job(
        self,
        print_job_id,
        *,
        operation_id=None,
        capture_id=None,
        manga_id=None,
    ):
        client = self.client or self._central_client()
        # Preview is deliberately read-only. The reservation happens here,
        # immediately before the irreversible interaction with the printer.
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
        try:
            success = bool(printer.print_tspl(tspl))
            state = "IMPRESA" if success else "FALLIDA_SIN_EMISION"
            error = None if success else "La impresora rechazo el trabajo"
        except Exception as exc:
            state = "EMISION_INCIERTA"
            error = str(exc)[:500]

        completed = datetime.now(timezone.utc)
        results = []
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
                completed_at_utc=completed,
                printer_name=printer_name,
                result=state,
                error_detail=error,
            )
            db.session.add(attempt)
            results.append({
                "label_id": label["public_id"],
                "estado": state,
                "printer_name": printer_name,
                "error": error,
            })
        db.session.commit()
        acknowledgement = client.acknowledge_scm_print_job(
            self._station_id(),
            job["print_job_id"],
            {"results": results},
        )
        return {
            "print_job": job,
            "tspl": tspl,
            "result": state,
            "central_ack": acknowledgement,
        }


def get_scm_prelabel_service():
    configured = current_app.config.get("SCM_PRELABEL_SERVICE")
    return configured or ScmPrelabelService()
