"""Fetch and print central PREPESAJE jobs without creating local weighings."""

import json
import hashlib
import base64
import io
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
    LABEL_HEIGHT_DOTS = 400
    TOP_BAR_Y = 14
    TEXT_START_Y = 18
    LINE_HEIGHT = 13
    QR_MODULE_DOTS = 4
    QR_QUIET_ZONE_MODULES = 4
    QR_GAP_Y = QR_MODULE_DOTS * QR_QUIET_ZONE_MODULES
    COMPACT_LAYOUT_VERSIONS = {
        "PREPESAJE_TSPL_4",
        "PREPESAJE_TSPL_5",
    }
    COMPACT_GENERAL_SIZE = 16
    COMPACT_MANGA_SIZE = 24
    COMPACT_MANGA_CODE_X = 75
    COMPACT_ROW_START_Y = 40
    COMPACT_LINE_HEIGHT = 17
    COMPACT_SEPARATOR_Y = 224
    COMPACT_QR_Y = 240

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

    @staticmethod
    def _qr_text(payload):
        qr_payload = payload["qr"]
        template = payload.get("template") or {}
        if template.get("qr_contract") != "LABEL_REF_V1":
            return json.dumps(
                qr_payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        return json.dumps(
            {
                "v": 1,
                "label_id": qr_payload["label_id"],
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _document_type(payload):
        if payload.get("document_type"):
            return str(payload["document_type"]).upper()
        return str((payload.get("qr") or {}).get("label_type") or "PREPESAJE").upper()

    @classmethod
    def _requires_qr(cls, payload):
        return cls._document_type(payload) == "PREPESAJE"

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
        rows = [
            ("MANGA", payload["codigo_manga"]),
            (order_label, order_ot),
            ("IMP.", printed_at),
            ("F.OT ORIG.", payload["fecha_ot"]),
            ("MAQ.ORIG.", payload["maquinista"]),
            ("PZA.", payload["pieza_color"]),
            ("COLOR", payload["color"]),
            ("TIPO", payload["tipo_manga"]),
            ("CANT.", payload["cantidad_planificada_un"]),
        ]
        return rows

    @classmethod
    def _uses_compact_layout(cls, payload):
        return (payload.get("template") or {}).get("version") in (
            cls.COMPACT_LAYOUT_VERSIONS
        )

    @classmethod
    def _compact_rows(cls, payload, printed_at):
        theoretical_kg = payload.get("kg_teoricos")
        if theoretical_kg is None:
            theoretical_kg = payload.get("kg_estimados")
        rows = [
            ("PZA", payload.get("pieza") or payload.get("pieza_color")),
            ("COLOR", payload.get("color")),
            (None, None),
        ]
        if payload.get("op"):
            rows.append(("OP", payload["op"]))
        rows.extend([
            ("MAQUINA", payload.get("maquina")),
            ("TIPO MANGA", payload.get("tipo_manga")),
            ("TURNO", payload.get("turno")),
            ("F.OT ORIG.", payload.get("fecha_ot")),
            ("OPE", payload.get("operador") or payload.get("maquinista")),
            ("IMP", printed_at),
            (
                "KG TEORICOS",
                f"{theoretical_kg} kg" if theoretical_kg is not None else None,
            ),
        ])
        return rows

    @staticmethod
    def _display_operational_datetime(payload, printed_at):
        raw_date = str(payload.get("fecha_ot") or "")
        try:
            operational_date = datetime.fromisoformat(raw_date).strftime(
                "%d/%m/%Y"
            )
        except ValueError:
            operational_date = raw_date
        time_value = str(printed_at or "").split(" ")[-1]
        return f"F.OT: {operational_date}  HORA: {time_value}"

    @classmethod
    def _weight_values(cls, payload):
        document_type = cls._document_type(payload)
        is_final = document_type == "POSTPESAJE"
        template_version = (payload.get("template") or {}).get("version")
        quantity_source = payload.get("fuente_cantidad")
        if not is_final:
            quantity_label = "CONTEO ACUMULADO"
        elif quantity_source == "PLAN_CONFIRMADO_POR_PESAJE":
            quantity_label = "CONTEO TEORICO"
        elif quantity_source in {
            "RESPONSABLE_ARMADO",
            "CIERRE_PARCIAL_SUPERVISADO",
            "CORRECCION_AUTORIZADA",
        }:
            quantity_label = "CONTEO CONFIRMADO"
        elif template_version == "POSTPESAJE_TSPL_5":
            # Los artefactos v5 creados antes de publicar fuente_cantidad
            # continúan legibles. En ausencia de evidencia explícita, el
            # cierre normal se presenta como teórico y no como conteo físico.
            quantity_label = (
                "CONTEO CONFIRMADO"
                if payload.get("cierre_parcial") or payload.get("oa_ot")
                else "CONTEO TEORICO"
            )
        else:
            # Compatibilidad con etiquetas anteriores que no publicaban la
            # procedencia del valor de unidades.
            quantity_label = "CONTEO FINAL"
        fabricated_theoretical = payload.get("peso_fabricado_teorico_kg")
        if fabricated_theoretical is None and template_version != (
            "POSTPESAJE_TSPL_5"
        ):
            fabricated_theoretical = payload.get("kg_produccion_ot")
        return {
            "title": (
                "FINAL · MANGA CERRADA"
                if is_final else "CONTROL · CONTINUA ABIERTA"
            ),
            "net_label": (
                "PESO NETO FINAL (kg)"
                if is_final else "PESO NETO REAL (kg)"
            ),
            "net": payload.get("peso_neto_real_kg") or payload.get("kg_fisico"),
            "contribution_label": (
                "APORTE ULTIMO TRAMO (kg)"
                if is_final else "APORTE DESDE CONTROL ANTERIOR (kg)"
            ),
            "contribution": payload.get("aporte_desde_control_anterior_kg"),
            "quantity_label": quantity_label,
            "quantity": (
                payload.get("cantidad_confirmada_un")
                if is_final else payload.get("cantidad_acumulada_un")
            ),
            "fabricated_theoretical": fabricated_theoretical,
            "shows_units": payload.get("cantidad_acumulada_un") is not None
            or is_final,
        }

    def _weight_column(self, x, item, printed_at):
        payload = item["payload"]
        values = self._weight_values(payload)
        order_label, order_value = self._order_row(payload)
        order_context = (
            f'OT CIERRE: {payload["ot_cierre"]}'
            if payload.get("ot_cierre")
            else f"{order_label}: {order_value}"
        )
        operational_datetime = self._display_operational_datetime(
            payload, printed_at
        )
        commands = [
            f"BOX {x + 1},2,{x + self.STICKER_WIDTH - 2},398,2",
            f'TEXT {x + 8},12,"2",0,1,1,"MANGA: {_safe(payload.get("codigo_manga"), 32)}"',
            f'TEXT {x + 8},38,"1",0,1,1,"{_safe(operational_datetime, 46)}"',
            f'TEXT {x + 8},58,"1",0,1,1,"MAQUINISTA: {_safe(payload.get("maquinista"), 31)}"',
            f'TEXT {x + 8},84,"2",0,1,1,"{values["net_label"]}"',
            f'TEXT {x + 62},108,"4",0,3,3,"{_safe(values["net"], 10)}"',
        ]
        if values["fabricated_theoretical"] is not None:
            commands.append(
                f'TEXT {x + 8},184,"1",0,1,1,'
                f'"PESO FABRICADO TEORICO (kg): '
                f'{_safe(values["fabricated_theoretical"], 9)}"'
            )
        commands.extend((
            f'BAR {x + 8},207,{self.STICKER_WIDTH - 16},2',
            f'TEXT {x + 8},218,"3",0,1,1,"{_safe(values["title"], 38)}"',
            f'TEXT {x + 8},246,"1",0,1,1,"{values["contribution_label"]}"',
            f'TEXT {x + 286},244,"3",0,1,2,"+{_safe(values["contribution"], 9)}"',
            f'TEXT {x + 8},276,"1",0,1,1,"{_safe(payload.get("pieza_color"), 46)}"',
        ))
        if values["shows_units"]:
            commands.extend((
                f'TEXT {x + 8},300,"2",0,1,1,"{values["quantity_label"]}: {_safe(values["quantity"], 10)} UN"',
                f'TEXT {x + 8},326,"1",0,1,1,"{_safe(order_context, 46)}"',
            ))
        else:
            commands.extend((
                f'TEXT {x + 8},300,"2",0,1,1,"AVANCE EN KG · SIN CONTEO"',
                f'TEXT {x + 8},326,"1",0,1,1,"{_safe(order_context, 46)}"',
            ))
        commands.append(
            f'TEXT {x + 8},375,"1",0,1,1,"SIN QR · CONSERVAR PREETIQUETA"'
        )
        return "\n".join(commands)

    def _column(self, x, item, printed_at):
        payload = item["payload"]
        if not self._requires_qr(payload):
            return self._weight_column(x, item, printed_at)
        if self._uses_compact_layout(payload):
            return self._compact_prelabel_column(x, item, printed_at)
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
            f'{self.QR_MODULE_DOTS},A,0,'
            f'"{_tspl_quoted(qr)}"'
        )
        return "\n".join(commands)

    def _compact_prelabel_column(self, x, item, printed_at):
        payload = item["payload"]
        qr_text = self._qr_text(payload)
        qr_size = self._qr_code(payload).modules_count * self.QR_MODULE_DOTS
        qr_x = x + (self.STICKER_WIDTH - qr_size) // 2
        if self.COMPACT_QR_Y + qr_size > self.LABEL_HEIGHT_DOTS:
            raise ValueError(
                "El QR SCM excede la altura fisica disponible de la etiqueta"
            )
        commands = [
            f"BOX {x + 1},2,{x + self.STICKER_WIDTH - 2},398,2",
            (
                f'TEXT {x + 7},10,"0",0,{self.COMPACT_GENERAL_SIZE},'
                f'{self.COMPACT_GENERAL_SIZE},"MANGA:"'
            ),
            (
                f'TEXT {x + self.COMPACT_MANGA_CODE_X},4,"0",0,'
                f'{self.COMPACT_MANGA_SIZE},{self.COMPACT_MANGA_SIZE},'
                f'"{_safe(payload.get("codigo_manga"), 24)}"'
            ),
        ]
        y = self.COMPACT_ROW_START_Y
        for label, value in self._compact_rows(payload, printed_at):
            if label is None:
                commands.append(
                    f"BAR {x + 7},{y},{self.STICKER_WIDTH - 16},2"
                )
                y += 5
                continue
            commands.append(
                f'TEXT {x + 7},{y},"0",0,{self.COMPACT_GENERAL_SIZE},'
                f'{self.COMPACT_GENERAL_SIZE},'
                f'"{label}: {_safe(value, 46)}"'
            )
            y += self.COMPACT_LINE_HEIGHT
        commands.extend((
            f"BAR {x + 1},{self.COMPACT_SEPARATOR_Y},"
            f"{self.STICKER_WIDTH - 3},2",
            (
                f'QRCODE {qr_x},{self.COMPACT_QR_Y},L,'
                f'{self.QR_MODULE_DOTS},A,0,'
                f'"{_tspl_quoted(qr_text)}"'
            ),
        ))
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
        if not self._requires_qr(payload):
            return self._svg_weight_column(x, item, printed_at)
        if self._uses_compact_layout(payload):
            return self._svg_compact_prelabel_column(x, item, printed_at)
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

    def _svg_compact_prelabel_column(self, x, item, printed_at):
        payload = item["payload"]
        qr_data_uri, qr_size = self._qr_data_uri(payload)
        qr_x = x + (self.STICKER_WIDTH - qr_size) // 2
        parts = [
            f'<rect x="{x + 1}" y="2" width="{self.STICKER_WIDTH - 3}" '
            f'height="396" rx="4" fill="white" stroke="#111" '
            'stroke-width="2"/>',
            f'<text x="{x + 7}" y="29" font-family="Arial, sans-serif" '
            f'font-size="{self.COMPACT_GENERAL_SIZE}" font-weight="700">'
            'MANGA:</text>',
            (
                f'<text x="{x + self.COMPACT_MANGA_CODE_X}" y="31" '
                'font-family="Arial Narrow, Arial, sans-serif" '
                f'font-size="{self.COMPACT_MANGA_SIZE}" font-weight="900">'
                f'{escape(_safe(payload.get("codigo_manga"), 24))}</text>'
            ),
        ]
        y = 54
        for label, value in self._compact_rows(payload, printed_at):
            if label is None:
                separator_y = y - 14
                parts.append(
                    f'<line x1="{x + 7}" y1="{separator_y}" '
                    f'x2="{x + self.STICKER_WIDTH - 9}" '
                    f'y2="{separator_y}" stroke="#111" stroke-width="2"/>'
                )
                y += 5
                continue
            parts.append(
                f'<text x="{x + 7}" y="{y}" '
                'font-family="Arial, sans-serif" '
                f'font-size="{self.COMPACT_GENERAL_SIZE}" font-weight="700">'
                f'{escape(f"{label}: {_safe(value, 46)}")}</text>'
            )
            y += self.COMPACT_LINE_HEIGHT
        parts.extend((
            f'<line x1="{x + 1}" y1="{self.COMPACT_SEPARATOR_Y}" '
            f'x2="{x + self.STICKER_WIDTH - 2}" '
            f'y2="{self.COMPACT_SEPARATOR_Y}" stroke="#111" '
            'stroke-width="2"/>',
            f'<image href="{qr_data_uri}" x="{qr_x}" '
            f'y="{self.COMPACT_QR_Y}" width="{qr_size}" '
            f'height="{qr_size}"/>',
        ))
        return "".join(parts)

    def _svg_weight_column(self, x, item, printed_at):
        payload = item["payload"]
        values = self._weight_values(payload)
        order_label, order_value = self._order_row(payload)
        order_context = (
            f'OT CIERRE: {payload["ot_cierre"]}'
            if payload.get("ot_cierre")
            else f"{order_label}: {order_value}"
        )
        operational_datetime = self._display_operational_datetime(
            payload, printed_at
        )
        text = lambda y, value, size=15, weight=600, anchor="start", x_pos=None: (
            f'<text x="{x_pos if x_pos is not None else x + 8}" y="{y}" '
            f'font-family="Arial, sans-serif" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}">'
            f'{escape(str(value or ""))}</text>'
        )
        parts = [
            f'<rect x="{x + 1}" y="2" width="{self.STICKER_WIDTH - 3}" '
            f'height="396" rx="4" '
            'fill="white" stroke="#111" stroke-width="3"/>',
            text(28, f'MANGA: {_safe(payload.get("codigo_manga"), 32)}', 18, 800),
            text(50, operational_datetime, 12, 600),
            text(70, f'MAQUINISTA: {_safe(payload.get("maquinista"), 31)}', 12, 700),
            text(98, values["net_label"], 18, 800),
            text(174, values["net"], 58, 900, "middle", x + 200),
        ]
        if values["fabricated_theoretical"] is not None:
            parts.append(text(
                198,
                f'PESO FABRICADO TEÓRICO (kg): {values["fabricated_theoretical"]}',
                13,
                700,
            ))
        parts.extend([
            f'<line x1="{x + 8}" y1="207" x2="{x + 392}" y2="207" '
            'stroke="#111" stroke-width="2"/>',
            text(232, values["title"], 20, 900),
            text(254, values["contribution_label"], 13, 700),
            text(270, f'+{values["contribution"]}', 24, 900, "end", x + 392),
            text(289, _safe(payload.get("pieza_color"), 46), 13, 600),
        ])
        if values["shows_units"]:
            parts.extend((
                text(313, f'{values["quantity_label"]}: {values["quantity"]} UN', 17, 800),
                text(337, order_context, 12, 600),
            ))
        else:
            parts.extend((
                text(313, 'AVANCE EN KG · SIN CONTEO', 18, 800),
                text(337, order_context, 12, 600),
            ))
        parts.append(text(386, 'SIN QR · CONSERVAR PREETIQUETA', 12, 800))
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
        client = self.client or self._central_client()
        # Preview is deliberately read-only. The reservation happens here,
        # immediately before the irreversible interaction with the printer.
        job = client.claim_scm_print_job(
            self._station_id(), print_job_id
        )
        attempted_at = datetime.now(timezone.utc)
        tspl = self.generate_tspl(job, printed_at=attempted_at)
        preview_svg = self.generate_preview_svg(job, printed_at=attempted_at)
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
            payload = label["payload"]
            qr_payload = payload.get("qr") or {}
            attempt = ScmLabelPrintAttempt(
                print_job_id=job["print_job_id"],
                label_id=label["public_id"],
                label_type=(
                    payload.get("document_type")
                    or qr_payload.get("label_type")
                    or label.get("tipo")
                ),
                operation_id=operation_id,
                capture_id=capture_id,
                manga_id=(
                    manga_id
                    or payload.get("manga_id")
                    or qr_payload.get("manga_id")
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
            "preview_svg": preview_svg,
        }


def get_scm_prelabel_service():
    configured = current_app.config.get("SCM_PRELABEL_SERVICE")
    return configured or ScmPrelabelService()
