"""
Servicio para generación de stickers con datos del pesaje.
Formato basado en el sistema antiguo de ENVAPERU.
"""
from datetime import datetime
from typing import Optional
from app.models.pesaje import Pesaje
from app.services.printer_service import get_printer_service


class StickerService:
    """Servicio para generar y enviar stickers a la impresora"""
    
    def generate_zpl(self, pesaje: Pesaje) -> str:
        """
        Genera código ZPL para impresoras Zebra.
        Formato basado en el sticker original de ENVAPERU.
        """
        fecha_hora = pesaje.fecha_hora.strftime('%Y-%m-%d/%H:%M:%S') if pesaje.fecha_hora else ''
        fecha_ot = pesaje.fecha_orden_trabajo.strftime('%Y-%m-%d') if pesaje.fecha_orden_trabajo else ''
        qr_data = pesaje.generate_sticker_qr_data()
        
        # Etiqueta de aproximadamente 60x40mm
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
        """
        Genera comandos ESC/POS para impresoras térmicas.
        Formato basado en el sticker original de ENVAPERU.
        """
        fecha_hora = pesaje.fecha_hora.strftime('%Y-%m-%d/%H:%M:%S') if pesaje.fecha_hora else ''
        fecha_ot = pesaje.fecha_orden_trabajo.strftime('%Y-%m-%d') if pesaje.fecha_orden_trabajo else ''
        
        # Comandos básicos ESC/POS
        ESC = b'\x1b'
        GS = b'\x1d'
        
        commands = b''
        commands += ESC + b'@'  # Initialize
        
        # Línea separadora superior
        commands += b'--------------------------------\n'
        
        # Datos del sticker
        commands += f"MOL : {pesaje.molde or ''}\n".encode('utf-8')
        commands += f"MAQ : {pesaje.maquina or ''}\n".encode('utf-8')
        commands += f"N°OP: {pesaje.nro_op or ''}\n".encode('utf-8')
        commands += f"TUR : {pesaje.turno or ''}\n".encode('utf-8')
        commands += f"F.OT: {fecha_ot}\n".encode('utf-8')
        commands += f"N°OT: {pesaje.nro_orden_trabajo or ''}\n".encode('utf-8')
        commands += f"OPE.: {pesaje.operador or ''}\n".encode('utf-8')
        commands += f"COL : {pesaje.color or ''}\n".encode('utf-8')
        commands += f"F./H.: {fecha_hora}\n".encode('utf-8')
        
        # Peso en tamaño grande
        commands += GS + b'!\x11'  # Double height + width
        commands += f"PESO {pesaje.peso_kg:.1f}\n".encode('utf-8')
        commands += GS + b'!\x00'  # Normal size
        
        # Línea separadora
        commands += b'--------------------------------\n'
        
        # TODO: Agregar QR code (requiere librería específica)
        # Por ahora solo texto del QR
        qr_data = pesaje.generate_sticker_qr_data()
        commands += f"QR: {qr_data[:30]}...\n".encode('utf-8')
        
        # Línea separadora inferior
        commands += b'--------------------------------\n'
        
        # Feed y corte
        commands += b'\n\n\n'
        commands += GS + b'V\x00'  # Full cut
        
        return commands
    
    def generate_sticker_text(self, pesaje: Pesaje) -> str:
        """
        Genera el texto del sticker para preview.
        """
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
        """
        Genera e imprime un sticker para el pesaje dado.
        """
        printer = get_printer_service()
        ptype = printer_type or printer.printer_type
        
        try:
            if ptype == 'ZPL':
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
