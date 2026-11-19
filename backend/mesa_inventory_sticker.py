"""Render TSPL/SVG para stickers de la estación 2.

El soporte de la TSC mide 109 x 50 mm: contiene dos stickers de 50 x 50 mm
en una sola fila. Cada copia repite *la misma* identidad/medición; no se
generan dos identidades ni dos trabajos de impresión.
"""

import re
import textwrap
from xml.etree import ElementTree as ET

import qrcode


MEDIA = "50x50"
PAPER_WIDTH_DOTS = 872  # 109 mm a 203 dpi
LABEL_WIDTH_DOTS = 400  # 50 mm a 203 dpi
LABEL_HEIGHT_DOTS = 400
LABEL_ORIGINS = (24, 464)  # 3 mm de margen y separación de 5 mm


def _safe_text(value):
    return " ".join(str(value).split()).replace('"', "'")


def render_sticker(unit, kind, media, output):
    """Renderiza una identidad en 2up horizontal.

    ``identidad`` imprime solo la identidad, ``pesaje`` imprime bruto/tara/neto
    de inventario y ``retorno`` imprime la medición neta de un retorno. El
    retorno no inventa bruto ni tara, que no existen en ese flujo.
    """
    if kind not in {"identidad", "pesaje", "retorno"} or media != MEDIA or output not in {"svg", "tspl"}:
        raise ValueError("Formato de etiqueta desconocido")
    code = unit.get("codigo", "")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,48}", code):
        raise ValueError("Código de manga inválido")
    if kind == "pesaje" and any(unit.get(k) is None for k in ("bruto", "tara", "neto")):
        raise ValueError("Primero registre el pesaje")
    if kind == "retorno" and unit.get("neto") is None:
        raise ValueError("Primero registre el retorno")

    two_up = kind != "identidad"
    preview_width = PAPER_WIDTH_DOTS if two_up else LABEL_WIDTH_DOTS
    preview_viewbox = f"0 0 {PAPER_WIDTH_DOTS} {LABEL_HEIGHT_DOTS}" if two_up else "24 0 400 400"
    svg = ET.Element(
        "svg",
        xmlns="http://www.w3.org/2000/svg",
        width="109mm" if two_up else "50mm",
        height="50mm",
        viewBox=preview_viewbox,
    )
    ET.SubElement(svg, "rect", x="0", y="0", width=str(preview_width), height=str(LABEL_HEIGHT_DOTS), fill="white")
    job = [
        "SIZE 109 mm, 50 mm",
        "GAP 3 mm, 0 mm",
        "DIRECTION 1",
        "REFERENCE 0,0",
        "SET TEAR ON",
        "OFFSET 0 mm",
        "CODEPAGE UTF-8",
        "CLS",
    ]

    def render_copy(origin):
        margin = origin + 34
        ink = LABEL_WIDTH_DOTS - 68
        svg_group = ET.SubElement(svg, "g", transform=f"translate({origin},0)")

        def line(x, y, value, scale=1):
            value = _safe_text(value)
            job.append(f'TEXT {x},{y},"2",0,{scale},{scale},"{value}"')
            item = ET.SubElement(
                svg_group,
                "text",
                x=str(x - origin),
                y=str(y + 17 * scale),
                fill="black",
                attrib={"font-family": "monospace", "font-size": str(20 * scale)},
            )
            item.text = value

        line(margin, 14, "ENVAPERU S.A.C.")
        line(margin, 40, {"identidad": "IDENTIDAD DE MANGA", "pesaje": "PESAJE DE INVENTARIO", "retorno": "RETORNO DE ARMADO"}[kind])
        y = 78
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
        qr.add_data(code)
        qr.make()
        matrix = qr.get_matrix()
        cell = 4
        size = len(matrix) * cell
        x = margin + (ink - size) // 2
        job.append(f'QRCODE {x},{y},M,{cell},A,0,"{code}"')
        svg_x = x - origin
        modules = "".join(
            f"M{svg_x + col * cell} {y + row * cell}h{cell}v{cell}h-{cell}z"
            for row, cells in enumerate(matrix)
            for col, dark in enumerate(cells)
            if dark
        )
        ET.SubElement(svg_group, "path", d=modules)
        y += size + 4 * cell
        if len(code) * 12 > ink:
            raise ValueError("El código excede el ancho de la etiqueta")
        line(margin + (ink - len(code) * 12) // 2, y, code)
        y += 25
        for field in ("pieza", "color", "zona"):
            if unit.get(field):
                for part in textwrap.wrap(_safe_text(unit[field]), width=ink // 12):
                    line(margin, y, part)
                    y += 24
        if kind == "pesaje":
            y += 4
            line(margin, y, f"Bruto {unit['bruto']} kg   Tara {unit['tara']} kg")
            y += 24
        if kind in {"pesaje", "retorno"}:
            y += 4
            net_label = f"Neto {unit['neto']} kg"
            net_zoom = 2 if y + 40 <= 394 and len(net_label) * 24 <= ink else 1
            line(margin, y, net_label, net_zoom)
            y += 20 * net_zoom
        if y > 394:
            raise ValueError("El detalle excede el área imprimible de 50 × 50 mm")

    for origin in LABEL_ORIGINS if two_up else (24,):
        render_copy(origin)

    return "\r\n".join([*job, "PRINT 1,1", ""]) if output == "tspl" else ET.tostring(svg, encoding="unicode")
