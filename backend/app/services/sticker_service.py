"""
Servicio para generación de stickers con datos del pesaje.
Formato basado en el sistema antiguo de ENVAPERU.
Soporta TSPL (TSC), ZPL (Zebra) y ESC/POS (térmicas).
"""
from datetime import datetime
from typing import Optional
from app.models.pesaje import Pesaje
from app.services.printer_service import get_printer_service


class StickerService:
    """Servicio para generar y enviar stickers a la impresora"""
    
    # Configuración TSPL
    MAX_CHARS_PER_LINE = 25  # Máximo caracteres por línea
    LEFT_X = 40              # Posición X sticker izquierdo
    RIGHT_X = 456            # Posición X sticker derecho
    LINE_HEIGHT = 18         # Altura entre líneas
    
    def _wrap_text(self, text: str, max_len: int = None) -> list:
        """Divide texto largo en múltiples líneas."""
        max_len = max_len or self.MAX_CHARS_PER_LINE
        if len(text) <= max_len:
            return [text]
        return [text[:max_len], text[max_len:max_len*2]]
    
    def generate_tspl(self, pesaje: Pesaje) -> str:
        """
        Genera código TSPL2 para impresoras TSC.
        Formato 2-up en papel de 105mm x 50mm.
        """
        fecha_hora = pesaje.fecha_hora.strftime('%Y-%m-%d/%H:%M:%S') if pesaje.fecha_hora else ''
        fecha_ot = pesaje.fecha_orden_trabajo.strftime('%Y-%m-%d') if pesaje.fecha_orden_trabajo else ''
        qr_data = self._build_qr_data(pesaje)
        
        # Procesar campos largos
        mol_lines = self._wrap_text(pesaje.molde or '')
        ope_lines = self._wrap_text(pesaje.operador or '')
        
        def gen_sticker(x: int) -> str:
            """Genera TSPL para un sticker en posición x."""
            y = 25  # Y inicial
            lines = []
            lines.append(f'BAR {x}, 20, 360, 3')  # Barra superior gruesa
            
            # MOL (puede ser 1 o 2 líneas)
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "MOL: {mol_lines[0]}"')
            y += self.LINE_HEIGHT
            if len(mol_lines) > 1:
                lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "     {mol_lines[1]}"')
                y += self.LINE_HEIGHT
            
            # Campos fijos
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "MAQ: {pesaje.maquina or ""}"')
            y += self.LINE_HEIGHT
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "NrOP: {pesaje.nro_op or ""}"')
            y += self.LINE_HEIGHT
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "TUR: {pesaje.turno or ""}"')
            y += self.LINE_HEIGHT
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "F.OT: {fecha_ot}"')
            y += self.LINE_HEIGHT
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "NrOT: {pesaje.nro_orden_trabajo or ""}"')
            y += self.LINE_HEIGHT
            
            # OPE (puede ser 1 o 2 líneas)
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "OPE: {ope_lines[0]}"')
            y += self.LINE_HEIGHT
            if len(ope_lines) > 1:
                lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "     {ope_lines[1]}"')
                y += self.LINE_HEIGHT
            
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "COL: {pesaje.color or ""}"')
            y += self.LINE_HEIGHT
            
            # Separador F/H
            lines.append(f'BAR {x}, {y}, 360, 2')
            y += 5
            lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "F/H: {fecha_hora}"')
            y += self.LINE_HEIGHT
            
            # Separador PESO
            lines.append(f'BAR {x}, {y}, 360, 2')
            y += 5
            lines.append(f'TEXT {x + 4}, {y}, "2", 0, 1, 1, "PESO: {pesaje.peso_kg:.1f}"')
            y += 28
            
            # QR
            lines.append(f'QRCODE {x + 120}, {y}, L, 3, A, 0, "{qr_data}"')
            y += 125
            
            # Barra final gruesa
            lines.append(f'BAR {x}, {y}, 360, 3')
            
            return '\n'.join(lines)
        
        # Generar comando completo
        tspl = f"""
SIZE 105 mm, 50 mm
GAP 2 mm, 0 mm
DIRECTION 1
CLS

; === STICKER IZQUIERDO ===
{gen_sticker(self.LEFT_X)}

; === STICKER DERECHO ===
{gen_sticker(self.RIGHT_X)}

PRINT 1,1
"""
        return tspl
    
    def _build_qr_data(self, pesaje: Pesaje) -> str:
        """Construye el contenido del QR para el sticker."""
        fecha_ot = pesaje.fecha_orden_trabajo.strftime('%Y-%m-%d') if pesaje.fecha_orden_trabajo else ''
        hora = pesaje.fecha_hora.strftime('%H:%M:%S') if pesaje.fecha_hora else ''
        
        return ';'.join([
            str(pesaje.id or ''),
            pesaje.molde or '',
            pesaje.maquina or '',
            pesaje.nro_op or '',
            pesaje.turno or '',
            fecha_ot,
            pesaje.nro_orden_trabajo or '',
            pesaje.operador or '',
            pesaje.color or '',
            f'{pesaje.peso_kg:.1f}',
            fecha_ot,
            hora
        ])
    
    def generate_zpl(self, pesaje: Pesaje) -> str:
        """Genera código ZPL para impresoras Zebra."""
        fecha_hora = pesaje.fecha_hora.strftime('%Y-%m-%d/%H:%M:%S') if pesaje.fecha_hora else ''
        fecha_ot = pesaje.fecha_orden_trabajo.strftime('%Y-%m-%d') if pesaje.fecha_orden_trabajo else ''
        qr_data = pesaje.generate_sticker_qr_data()
        
        zpl = f"""
^XA
^CF0,25
^FO20,20^FDMOL : {pesaje.molde or ''}^FS
^FO20,50^FDMAQ : {pesaje.maquina or ''}^FS
^FO20,80^FDN°OP: {pesaje.nro_op or ''}^FS
^FO20,110^FDTUR : {pesaje.turno or ''}^FS
^FO20,140^FDF.OT: {fecha_ot}^FS
^FO20,170^FDN°OT: {pesaje.nro_orden_trabajo or ''}^FS
^FO20,200^FDOPE.: {pesaje.operador or ''}^FS
^FO20,230^FDCOL : {pesaje.color or ''}^FS
^FO20,260^FDF./H.: {fecha_hora}^FS
^CF0,40
^FO20,300^FDPESO {pesaje.peso_kg:.1f}^FS
^FO20,360^BY2
^BQN,2,4
^FDQA,{qr_data}^FS
^XZ
"""
        return zpl.strip()
    
    def generate_escpos(self, pesaje: Pesaje) -> bytes:
        """Genera comandos ESC/POS para impresoras térmicas."""
        fecha_hora = pesaje.fecha_hora.strftime('%Y-%m-%d/%H:%M:%S') if pesaje.fecha_hora else ''
        fecha_ot = pesaje.fecha_orden_trabajo.strftime('%Y-%m-%d') if pesaje.fecha_orden_trabajo else ''
        
        ESC = b'\x1b'
        GS = b'\x1d'
        
        commands = b''
        commands += ESC + b'@'  # Initialize
        commands += b'--------------------------------\n'
        commands += f"MOL : {pesaje.molde or ''}\n".encode('utf-8')
        commands += f"MAQ : {pesaje.maquina or ''}\n".encode('utf-8')
        commands += f"N°OP: {pesaje.nro_op or ''}\n".encode('utf-8')
        commands += f"TUR : {pesaje.turno or ''}\n".encode('utf-8')
        commands += f"F.OT: {fecha_ot}\n".encode('utf-8')
        commands += f"N°OT: {pesaje.nro_orden_trabajo or ''}\n".encode('utf-8')
        commands += f"OPE.: {pesaje.operador or ''}\n".encode('utf-8')
        commands += f"COL : {pesaje.color or ''}\n".encode('utf-8')
        commands += f"F./H.: {fecha_hora}\n".encode('utf-8')
        commands += GS + b'!\x11'  # Double height + width
        commands += f"PESO {pesaje.peso_kg:.1f}\n".encode('utf-8')
        commands += GS + b'!\x00'  # Normal size
        commands += b'--------------------------------\n'
        commands += b'\n\n\n'
        commands += GS + b'V\x00'  # Full cut
        
        return commands
    
    def generate_sticker_text(self, pesaje: Pesaje) -> str:
        """Genera el texto del sticker para preview."""
        fecha_hora = pesaje.fecha_hora.strftime('%Y-%m-%d/%H:%M:%S') if pesaje.fecha_hora else ''
        fecha_ot = pesaje.fecha_orden_trabajo.strftime('%Y-%m-%d') if pesaje.fecha_orden_trabajo else ''
        
        lines = [
            '─' * 32,
            f"MOL : {pesaje.molde or ''}",
            f"MÁQ : {pesaje.maquina or ''}",
            f"N°OP: {pesaje.nro_op or ''}",
            f"TUR : {pesaje.turno or ''}",
            f"F.OT: {fecha_ot}",
            f"N°OT: {pesaje.nro_orden_trabajo or ''}",
            f"OPE.: {pesaje.operador or ''}",
            f"COL : {pesaje.color or ''}",
            f"F./H.: {fecha_hora}",
            f"PESO {pesaje.peso_kg:.1f}",
            '─' * 32,
            "[QR CODE]",
            '─' * 32,
        ]
        return '\n'.join(lines)
    
    def print_sticker(self, pesaje: Pesaje, printer_type: str = None) -> bool:
        """Genera e imprime un sticker para el pesaje dado."""
        printer = get_printer_service()
        ptype = printer_type or printer.printer_type
        
        try:
            if ptype == 'TSPL':
                tspl = self.generate_tspl(pesaje)
                return printer.print_tspl(tspl)
            elif ptype == 'ZPL':
                zpl = self.generate_zpl(pesaje)
                return printer.print_zpl(zpl)
            else:  # ESC_POS por defecto
                commands = self.generate_escpos(pesaje)
                return printer.print_escpos(commands)
        except Exception as e:
            print(f"Error imprimiendo sticker: {e}")
            return False


# Instancia global
_sticker_service: Optional[StickerService] = None


def get_sticker_service() -> StickerService:
    """Obtiene la instancia del servicio de stickers"""
    global _sticker_service
    if _sticker_service is None:
        _sticker_service = StickerService()
    return _sticker_service
