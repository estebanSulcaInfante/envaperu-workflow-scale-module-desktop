#!/usr/bin/env python3
"""
Preview rápido del sticker TSPL como imagen PNG.
Ejecutar: python preview_sticker.py
Genera previews tanto del sticker de PESAJE como del de RDP.
"""
from PIL import Image, ImageDraw, ImageFont
import qrcode
import subprocess
import sys
from datetime import datetime, date

# ── Datos de ejemplo ──────────────────────────────────────────────
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

# ── Configuración visual (misma que TSPL) ─────────────────────────
DPI = 203  # DPI típico de TSC (8 dots/mm)
PAPER_W = int(109 * DPI / 25.4)  # ~870 px
PAPER_H = int(50 * DPI / 25.4)   # ~400 px
STICKER_W = 400
LEFT_X = 24
RIGHT_X = 464  # 5mm gap entre stickers
DIECUT_X = 448  # Donde está el corte físico del papel (3mm después del sticker izq)
LINE_H = 18
BG_COLOR = "white"
TEXT_COLOR = "black"
RED = "#FF0000"
BLUE = "#0066CC"


def get_fonts():
    """Carga fuentes monospace."""
    paths = [
        "/usr/share/fonts/TTF/DejaVuSansMono",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono",
    ]
    for base in paths:
        try:
            normal = ImageFont.truetype(f"{base}.ttf", 13)
            bold = ImageFont.truetype(f"{base}-Bold.ttf", 18)
            return normal, bold
        except OSError:
            continue
    default = ImageFont.load_default()
    return default, default


def render_pesaje_sticker(draw, x_offset, datos, fonts):
    """Renderiza un sticker de PESAJE en posición x_offset."""
    font_normal, font_bold = fonts
    fecha_hora = datetime.now().strftime("%Y-%m-%d/%H:%M:%S")
    y = 25
    x = x_offset + 4

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
        y += LINE_H

    # Separador F/H
    draw.rectangle([x_offset, y, x_offset + STICKER_W, y + 2], fill=TEXT_COLOR)
    y += 5
    draw.text((x, y), f"F/H: {fecha_hora}", fill=TEXT_COLOR, font=font_normal)
    y += LINE_H

    # Separador peso
    draw.rectangle([x_offset, y, x_offset + STICKER_W, y + 2], fill=TEXT_COLOR)
    y += 5
    draw.text((x, y), f"PESO: {datos['peso_kg']:.1f}", fill=TEXT_COLOR, font=font_bold)
    y += 28

    # QR
    qr_data = ";".join([
        "1", datos["molde"], datos["maquina"], datos["nro_op"],
        datos["turno"], datos["fecha_ot"], datos["nro_ot"],
        datos["operador"], datos["color"], f"{datos['peso_kg']:.1f}",
        datos["fecha_ot"], datetime.now().strftime("%H:%M:%S")
    ])
    qr = qrcode.make(qr_data, box_size=2, border=1).resize((120, 120))
    return y, qr, x_offset + 120


def render_rdp_sticker(draw, x_offset, datos, fonts):
    """Renderiza un sticker de RDP en posición x_offset."""
    font_normal, font_bold = fonts
    y = 20
    x = x_offset + 4

    # Barra superior
    draw.rectangle([x_offset, y, x_offset + STICKER_W, y + 3], fill=TEXT_COLOR)
    y += 8

    # Título
    draw.text((x, y), "REG. DIARIO PROD.", fill=TEXT_COLOR, font=font_bold)
    y += 28

    # Separador
    draw.rectangle([x_offset, y, x_offset + STICKER_W, y + 2], fill=TEXT_COLOR)
    y += 5

    # Campos
    fields = [
        f"NrOT: {datos['nro_ot']}",
        f"NrOP: {datos['nro_op']}",
        f"MOL: {datos['molde']}",
        f"MAQ: {datos['maquina']}",
        f"TUR: {datos['turno']}",
        f"FECHA: {datos['fecha_ot']}",
    ]
    for field in fields:
        draw.text((x, y), field, fill=TEXT_COLOR, font=font_normal)
        y += LINE_H

    # Separador QR
    draw.rectangle([x_offset, y, x_offset + STICKER_W, y + 2], fill=TEXT_COLOR)
    y += 5

    # QR (más grande para RDP)
    qr_data = ";".join([
        "0", datos["molde"], datos["maquina"], datos["nro_op"],
        datos["turno"], datos["fecha_ot"], datos["nro_ot"], ""
    ])
    qr = qrcode.make(qr_data, box_size=3, border=1).resize((130, 130))
    return y, qr, x_offset + 90


def draw_dimensions(draw, paper_w, paper_h, y_base):
    """Dibuja etiquetas de dimensiones."""
    font_normal, _ = get_fonts()
    gray = "#888888"
    
    # Margen izq
    draw.text((2, y_base + paper_h + 5), "3mm", fill=gray, font=font_normal)
    # Gap
    gap_x = LEFT_X + STICKER_W + 5
    draw.text((gap_x, y_base + paper_h + 5), "5mm", fill=gray, font=font_normal)
    # Margen der
    draw.text((paper_w - 25, y_base + paper_h + 5), "1mm", fill=gray, font=font_normal)


def main():
    fonts = get_fonts()
    
    # Imagen con espacio para ambos previews (pesaje arriba, RDP abajo)
    total_h = PAPER_H * 2 + 80  # espacio entre ambos
    img = Image.new("RGB", (PAPER_W, total_h), "#F5F5F5")
    draw = ImageDraw.Draw(img)
    font_normal, font_bold = fonts

    # ═══ STICKER DE PESAJE ═══
    draw.text((PAPER_W // 2 - 80, 2), "STICKER DE PESAJE", fill="#333", font=font_bold)
    y_base_pesaje = 22

    # Fondo papel
    draw.rectangle([0, y_base_pesaje, PAPER_W - 1, y_base_pesaje + PAPER_H - 1], fill=BG_COLOR, outline="#CCC")

    # Crear sub-imagen para sticker de pesaje
    pesaje_img = Image.new("RGB", (PAPER_W, PAPER_H), BG_COLOR)
    pesaje_draw = ImageDraw.Draw(pesaje_img)
    pesaje_draw.rectangle([0, 0, PAPER_W-1, PAPER_H-1], outline="#CCC", width=1)

    # Sticker izquierdo
    y1, qr1, qr_x1 = render_pesaje_sticker(pesaje_draw, LEFT_X, DATOS, fonts)
    pesaje_img.paste(qr1, (qr_x1, y1))

    # Sticker derecho
    y2, qr2, qr_x2 = render_pesaje_sticker(pesaje_draw, RIGHT_X, DATOS, fonts)
    pesaje_img.paste(qr2, (qr_x2, y2))

    # Líneas de corte físico (die-cut) y dimensiones
    # Corte izquierdo del gap
    pesaje_draw.line([(LEFT_X + STICKER_W, 0), (LEFT_X + STICKER_W, PAPER_H)], fill=RED, width=1)
    # Corte derecho del gap (donde empieza el área del sticker derecho)
    pesaje_draw.line([(DIECUT_X, 0), (DIECUT_X, PAPER_H)], fill=RED, width=1)
    # Línea donde empieza el contenido del sticker derecho
    pesaje_draw.line([(RIGHT_X, 0), (RIGHT_X, PAPER_H)], fill=BLUE, width=1)
    # Labels
    try:
        font_tiny = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 9)
    except OSError:
        font_tiny = ImageFont.load_default()
    pesaje_draw.text((LEFT_X + STICKER_W + 2, 2), "3mm", fill=RED, font=font_tiny)
    pesaje_draw.text((LEFT_X + STICKER_W + 2, 12), "gap", fill=RED, font=font_tiny)
    pesaje_draw.text((DIECUT_X + 2, 2), "2mm", fill=BLUE, font=font_tiny)
    pesaje_draw.text((DIECUT_X + 2, 12), "pad", fill=BLUE, font=font_tiny)

    img.paste(pesaje_img, (0, y_base_pesaje))

    # ═══ STICKER DE RDP ═══
    y_base_rdp = y_base_pesaje + PAPER_H + 40
    draw.text((PAPER_W // 2 - 65, y_base_rdp - 18), "STICKER DE RDP", fill="#333", font=font_bold)

    rdp_img = Image.new("RGB", (PAPER_W, PAPER_H), BG_COLOR)
    rdp_draw = ImageDraw.Draw(rdp_img)
    rdp_draw.rectangle([0, 0, PAPER_W-1, PAPER_H-1], outline="#CCC", width=1)

    # Sticker izquierdo
    y3, qr3, qr_x3 = render_rdp_sticker(rdp_draw, LEFT_X, DATOS, fonts)
    rdp_img.paste(qr3, (qr_x3, y3))

    # Sticker derecho
    y4, qr4, qr_x4 = render_rdp_sticker(rdp_draw, RIGHT_X, DATOS, fonts)
    rdp_img.paste(qr4, (qr_x4, y4))

    # Líneas de corte físico y dimensiones
    rdp_draw.line([(LEFT_X + STICKER_W, 0), (LEFT_X + STICKER_W, PAPER_H)], fill=RED, width=1)
    rdp_draw.line([(DIECUT_X, 0), (DIECUT_X, PAPER_H)], fill=RED, width=1)
    rdp_draw.line([(RIGHT_X, 0), (RIGHT_X, PAPER_H)], fill=BLUE, width=1)
    try:
        font_tiny = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 9)
    except OSError:
        font_tiny = ImageFont.load_default()
    rdp_draw.text((LEFT_X + STICKER_W + 2, 2), "3mm", fill=RED, font=font_tiny)
    rdp_draw.text((LEFT_X + STICKER_W + 2, 12), "gap", fill=RED, font=font_tiny)
    rdp_draw.text((DIECUT_X + 2, 2), "2mm", fill=BLUE, font=font_tiny)
    rdp_draw.text((DIECUT_X + 2, 12), "pad", fill=BLUE, font=font_tiny)

    img.paste(rdp_img, (0, y_base_rdp))

    # ═══ Guardar ═══
    output = "/tmp/sticker_preview_both.png"
    img_scaled = img.resize((PAPER_W * 2, total_h * 2), Image.NEAREST)
    img_scaled.save(output)
    print(f"✅ Preview guardado en: {output}")
    print(f"   Papel: 109mm x 50mm | LEFT_X={LEFT_X} | RIGHT_X={RIGHT_X}")
    print(f"   Gap: {RIGHT_X - LEFT_X - STICKER_W} dots = {(RIGHT_X - LEFT_X - STICKER_W) / 8:.0f}mm")
    print(f"   Margen der: {PAPER_W - RIGHT_X - STICKER_W} dots = {(PAPER_W - RIGHT_X - STICKER_W) / 8:.1f}mm")

    # Intentar abrir
    try:
        subprocess.Popen(["xdg-open", output], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("🖼️  Abriendo preview...")
    except Exception:
        print(f"   Abre manualmente: {output}")


if __name__ == "__main__":
    main()
