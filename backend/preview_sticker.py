#!/usr/bin/env python3
"""
Preview rápido del sticker TSPL como imagen PNG.
Ejecutar: python preview_sticker.py
Se abre automáticamente en el visor de imágenes del sistema.
"""
from PIL import Image, ImageDraw, ImageFont
import qrcode
import subprocess
import sys
from datetime import datetime, date

# ── Datos de ejemplo (edita según necesites) ──────────────────────
DATOS = {
    "molde": "CERNIDOR ROMANO",
    "maquina": "HT-250B",
    "nro_op": "OP1354",
    "turno": "DIURNO",
    "fecha_ot": "2026-03-02",
    "nro_ot": "0001",
    "operador": "JUAN PEREZ GARCIA",
    "color": "NATURAL",
    "peso_kg": 25.5,
}

# ── Configuración visual ──────────────────────────────────────────
DPI = 203  # DPI típico de TSC (8 dots/mm)
# Papel: 109mm x 50mm → en pixels a 203 DPI
PAPER_W = int(109 * DPI / 25.4)  # ~870 px
PAPER_H = int(50 * DPI / 25.4)   # ~400 px
STICKER_W = 400  # dots (como en TSPL)
MARGIN = 24
BG_COLOR = "white"
TEXT_COLOR = "black"


def render_sticker(draw: ImageDraw.Draw, x_offset: int, datos: dict):
    """Renderiza un sticker individual en la posición x_offset."""
    fecha_hora = datetime.now().strftime("%Y-%m-%d/%H:%M:%S")
    y = 25

    # Fuentes (monospace para simular impresora térmica)
    try:
        font_normal = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSansMono.ttf", 13)
        font_bold = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf", 18)
    except OSError:
        try:
            font_normal = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 13)
            font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 18)
        except OSError:
            font_normal = ImageFont.load_default()
            font_bold = font_normal

    x = x_offset + 4
    line_h = 18

    # Barra superior
    draw.rectangle([x_offset, 20, x_offset + STICKER_W, 23], fill=TEXT_COLOR)

    # Campos
    fields = [
        f"MOL: {datos['molde']}",
        f"MAQ: {datos['maquina']}",
        f"NrOP: {datos['nro_op']}",
        f"TUR: {datos['turno']}",
        f"F.OT: {datos['fecha_ot']}",
        f"NrOT: {datos['nro_ot']}",
        f"OPE: {datos['operador']}",
        f"COL: {datos['color']}",
    ]

    for field in fields:
        draw.text((x, y), field, fill=TEXT_COLOR, font=font_normal)
        y += line_h

    # Separador
    draw.rectangle([x_offset, y, x_offset + STICKER_W, y + 2], fill=TEXT_COLOR)
    y += 5
    draw.text((x, y), f"F/H: {fecha_hora}", fill=TEXT_COLOR, font=font_normal)
    y += line_h

    # Separador peso
    draw.rectangle([x_offset, y, x_offset + STICKER_W, y + 2], fill=TEXT_COLOR)
    y += 5
    draw.text((x, y), f"PESO: {datos['peso_kg']:.1f}", fill=TEXT_COLOR, font=font_bold)
    y += 28

    # QR code
    qr_data = ";".join([
        "1", datos["molde"], datos["maquina"], datos["nro_op"],
        datos["turno"], datos["fecha_ot"], datos["nro_ot"],
        datos["operador"], datos["color"], f"{datos['peso_kg']:.1f}",
        datos["fecha_ot"], datetime.now().strftime("%H:%M:%S")
    ])
    qr = qrcode.make(qr_data, box_size=2, border=1)
    qr = qr.resize((100, 100))

    # Pegar QR en la imagen principal (necesitamos acceso a la imagen)
    return y, qr, x_offset + 120


def main():
    # Crear imagen del papel completo
    img = Image.new("RGB", (PAPER_W, PAPER_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Borde del papel (visual)
    draw.rectangle([0, 0, PAPER_W-1, PAPER_H-1], outline="#CCCCCC", width=1)

    # Sticker izquierdo
    y1, qr1, qr_x1 = render_sticker(draw, MARGIN, DATOS)
    img.paste(qr1, (qr_x1, y1))

    barra_y1 = y1 + 105
    draw.rectangle([MARGIN, barra_y1, MARGIN + STICKER_W, barra_y1 + 3], fill=TEXT_COLOR)

    # Sticker derecho
    y2, qr2, qr_x2 = render_sticker(draw, 456, DATOS)
    img.paste(qr2, (qr_x2, y2))

    barra_y2 = y2 + 105
    draw.rectangle([456, barra_y2, 456 + STICKER_W, barra_y2 + 3], fill=TEXT_COLOR)

    # Línea divisoria central (visual)
    draw.line([(PAPER_W // 2, 5), (PAPER_W // 2, PAPER_H - 5)], fill="#DDDDDD", width=1)

    # Guardar y abrir
    output = "/tmp/sticker_preview.png"
    # Escalar 2x para mejor visualización
    img_scaled = img.resize((PAPER_W * 2, PAPER_H * 2), Image.NEAREST)
    img_scaled.save(output)
    print(f"✅ Sticker guardado en: {output}")
    print(f"   Tamaño papel: {109}mm x {50}mm")
    print(f"   Resolución: {PAPER_W}x{PAPER_H} dots @ {DPI} DPI")

    # Intentar abrir automáticamente
    try:
        subprocess.Popen(["xdg-open", output], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("🖼️  Abriendo preview...")
    except Exception:
        print(f"   Abre manualmente: {output}")


if __name__ == "__main__":
    main()
