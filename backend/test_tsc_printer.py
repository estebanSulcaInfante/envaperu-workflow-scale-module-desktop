"""
Script de prueba para imprimir en TSC T200 via Windows RAW.
Usa comandos TSPL2 para generar etiquetas de producción.

Uso:
    cd backend
    .\venv\Scripts\Activate.ps1
    python test_tsc_printer.py
"""
import sys


def list_windows_printers():
    """Lista las impresoras instaladas en Windows."""
    try:
        import win32print
        printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
        print("\n📋 Impresoras disponibles en Windows:")
        for p in printers:
            print(f"   - {p[2]}")
        return [p[2] for p in printers]
    except ImportError:
        print("❌ Instala pywin32: pip install pywin32")
        return []


def print_via_windows_raw(printer_name: str, tspl_data: str):
    """Imprimir via Windows RAW."""
    try:
        import win32print
        
        # Abrir impresora
        handle = win32print.OpenPrinter(printer_name)
        
        try:
            # Iniciar documento RAW
            win32print.StartDocPrinter(handle, 1, ("Label", None, "RAW"))
            
            try:
                win32print.StartPagePrinter(handle)
                win32print.WritePrinter(handle, tspl_data.encode('utf-8'))
                win32print.EndPagePrinter(handle)
                print(f"✅ Impresión enviada a {printer_name}")
                return True
                
            finally:
                win32print.EndDocPrinter(handle)
                
        finally:
            win32print.ClosePrinter(handle)
            
    except ImportError:
        print("❌ Instala pywin32: pip install pywin32")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def generate_tspl_label(
    molde: str = "CERNIDOR ROMANO",
    maquina: str = "HT-250B",
    nro_op: str = "OP-1354",
    turno: str = "DIURNO",
    fecha_ot: str = "2026-01-03",
    nro_ot: str = "0000",
    operador: str = "Admin",
    color: str = "",
    fecha_hora: str = "2026-01-03/9:49:13",
    peso: str = "71",
    registro_id: str = "4599"
) -> str:
    """
    Genera comandos TSPL2 para imprimir etiqueta estilo producción.
    
    Medidas (TSC TE200 a 203 DPI = 8 dots/mm):
    - Papel: 105mm ancho (840 dots)
    - Etiqueta: 50mm x 50mm (400 x 400 dots)
    - 2 columnas: izquierda 0-52mm, derecha 53-105mm
    - Max ~25 caracteres por línea (sin incluir label)
    """
    
    # QR data (separado por ;) - formato legacy
    qr_data = f"{registro_id};{molde};{maquina};{nro_op};{turno};{fecha_ot};{nro_ot};{operador};{color};{peso};{fecha_ot};{fecha_hora.split('/')[-1] if '/' in fecha_hora else fecha_hora}"
    
    # Config
    MAX_CHARS = 25  # máximo caracteres por línea después del label
    left_x = 40
    right_x = 456
    line_y = 25  # posición Y inicial
    line_h = 18  # altura entre líneas
    
    # Wrap text helper
    def wrap_text(text, max_len):
        if len(text) <= max_len:
            return [text]
        return [text[:max_len], text[max_len:max_len*2]]
    
    # Procesar campos largos
    mol_lines = wrap_text(molde, MAX_CHARS)
    ope_lines = wrap_text(operador, MAX_CHARS)
    
    def gen_sticker(x):
        """Genera TSPL para un sticker en posición x."""
        y = line_y
        lines = []
        lines.append(f'BAR {x}, 20, 360, 3')  # Barra superior gruesa
        
        # MOL (puede ser 1 o 2 líneas)
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "MOL: {mol_lines[0]}"')
        y += line_h
        if len(mol_lines) > 1:
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "     {mol_lines[1]}"')
            y += line_h
        
        # Campos fijos con nombres correctos
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "MAQ: {maquina}"')
        y += line_h
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "NrOP: {nro_op}"')
        y += line_h
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "TUR: {turno}"')
        y += line_h
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "F.OT: {fecha_ot}"')
        y += line_h
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "NrOT: {nro_ot}"')
        y += line_h
        
        # OPE (puede ser 1 o 2 líneas)
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "OPE: {ope_lines[0]}"')
        y += line_h
        if len(ope_lines) > 1:
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "     {ope_lines[1]}"')
            y += line_h
        
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "COL: {color}"')
        y += line_h
        
        # Separador F/H
        lines.append(f'BAR {x}, {y}, 360, 2')
        y += 5
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "F/H: {fecha_hora}"')
        y += line_h
        
        # Separador PESO
        lines.append(f'BAR {x}, {y}, 360, 2')
        y += 5
        lines.append(f'TEXT {x + 4}, {y}, "2", 0, 1, 1, "PESO: {peso}"')
        y += 28
        
        # QR
        lines.append(f'QRCODE {x + 120}, {y}, L, 3, A, 0, "{qr_data}"')
        y += 125
        
        # Barra final gruesa
        lines.append(f'BAR {x}, {y}, 360, 3')
        
        return '\n'.join(lines)
    
    # TSPL2 Commands
    tspl = f"""
SIZE 105 mm, 50 mm
GAP 2 mm, 0 mm
DIRECTION 1
CLS

; === STICKER IZQUIERDO ===
{gen_sticker(left_x)}

; === STICKER DERECHO ===
{gen_sticker(right_x)}

PRINT 1,1
"""
    return tspl


if __name__ == "__main__":
    print("=" * 50)
    print("🖨️  TSC TE200 - Script de Prueba de Impresión")
    print("=" * 50)
    
    # Datos de prueba (molde largo para probar wrap)
    label_data = {
        "molde": "CERNIDOR ROMANO GRANDE AZUL",  # 27 chars - probará wrap
        "maquina": "HT-250B",
        "nro_op": "OP-1354",
        "turno": "DIURNO",
        "fecha_ot": "2026-01-03",
        "nro_ot": "0000",
        "operador": "Admin",
        "color": "NATURAL",
        "fecha_hora": "2026-01-03/9:49:13",
        "peso": "71",
        "registro_id": "4599"
    }
    
    # Generar TSPL
    tspl = generate_tspl_label(**label_data)
    print("\n📄 Comandos TSPL generados:")
    print("-" * 40)
    print(tspl[:500] + "..." if len(tspl) > 500 else tspl)
    print("-" * 40)
    
    # Guardar a archivo para debug
    with open("test_label.tspl", "w") as f:
        f.write(tspl)
    print("💾 Guardado en test_label.tspl")
    
    # Buscar impresora
    print("\n🔍 Buscando impresora TSC...")
    printers = list_windows_printers()
    
    tsc_printer = None
    for p in printers:
        if "TSC" in p.upper() or "T200" in p.upper():
            tsc_printer = p
            break
    
    if tsc_printer:
        print(f"\n🖨️  Impresora TSC encontrada: {tsc_printer}")
        response = input("¿Imprimir etiqueta de prueba? (s/n): ")
        if response.lower() == 's':
            print_via_windows_raw(tsc_printer, tspl)
    else:
        print("\n⚠️  No se encontró impresora TSC automáticamente.")
        print("   Puedes especificar el nombre manualmente.")
        
        if printers:
            try:
                idx = int(input("Ingresa el número de impresora (0, 1, 2...): "))
                if 0 <= idx < len(printers):
                    response = input(f"¿Imprimir en '{printers[idx]}'? (s/n): ")
                    if response.lower() == 's':
                        print_via_windows_raw(printers[idx], tspl)
            except ValueError:
                print("Número inválido")
