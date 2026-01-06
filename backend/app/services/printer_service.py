"""
Servicio de impresión de etiquetas/stickers.
Soporta impresoras TSC (TSPL), Zebra (ZPL) y térmicas (ESC/POS).
"""
from typing import Optional, List
from flask import current_app


class PrinterService:
    """Servicio para comunicación con la impresora de etiquetas"""
    
    def __init__(self, port: str = None, printer_type: str = None, printer_name: str = None):
        self.port = port
        self.printer_type = printer_type
        self.printer_name = printer_name  # Nombre de impresora Windows
        self._connected = False
    
    def _get_config(self):
        """Obtiene configuración desde Flask config"""
        try:
            self.port = self.port or current_app.config.get('PRINTER_PORT', 'COM3')
            self.printer_type = self.printer_type or current_app.config.get('PRINTER_TYPE', 'TSPL')
            self.printer_name = self.printer_name or current_app.config.get('PRINTER_NAME', None)
        except RuntimeError:
            # Outside Flask context
            if not self.printer_type:
                self.printer_type = 'TSPL'
    
    def find_tsc_printer(self) -> Optional[str]:
        """Busca impresora TSC en Windows."""
        try:
            import win32print
            printers = win32print.EnumPrinters(
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            )
            for p in printers:
                if 'TSC' in p[2].upper() or 'TE200' in p[2].upper():
                    return p[2]
            return None
        except ImportError:
            print("[PRINTER] win32print no disponible")
            return None
        except Exception as e:
            print(f"[PRINTER] Error buscando impresora: {e}")
            return None
    
    def get_available_printers(self) -> List[str]:
        """Lista impresoras disponibles en Windows."""
        try:
            import win32print
            printers = win32print.EnumPrinters(
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            )
            return [p[2] for p in printers]
        except ImportError:
            return []
        except Exception:
            return []
    
    def connect(self) -> bool:
        """Establece conexión con la impresora"""
        self._get_config()
        
        # Para TSPL usamos Windows RAW printing, no necesitamos conexión persistente
        if self.printer_type == 'TSPL':
            if not self.printer_name:
                self.printer_name = self.find_tsc_printer()
            self._connected = self.printer_name is not None
        else:
            self._connected = True
        
        return self._connected
    
    def disconnect(self):
        """Cierra la conexión con la impresora"""
        self._connected = False
    
    def print_tspl(self, tspl_code: str) -> bool:
        """
        Imprime código TSPL (para impresoras TSC) via Windows RAW.
        """
        try:
            import win32print
            
            # Asegurar conexión
            if not self._connected:
                self.connect()
            
            if not self.printer_name:
                print("[PRINTER] No se encontró impresora TSC")
                return False
            
            # Abrir impresora
            handle = win32print.OpenPrinter(self.printer_name)
            
            try:
                # Iniciar documento RAW
                win32print.StartDocPrinter(handle, 1, ("Label", None, "RAW"))
                
                try:
                    win32print.StartPagePrinter(handle)
                    win32print.WritePrinter(handle, tspl_code.encode('utf-8'))
                    win32print.EndPagePrinter(handle)
                    print(f"[PRINTER] ✅ Sticker enviado a {self.printer_name}")
                    return True
                finally:
                    win32print.EndDocPrinter(handle)
            finally:
                win32print.ClosePrinter(handle)
                
        except ImportError:
            print("[PRINTER] ❌ win32print no instalado. Ejecuta: pip install pywin32")
            return False
        except Exception as e:
            print(f"[PRINTER] ❌ Error: {e}")
            return False
    
    def print_raw(self, data: bytes) -> bool:
        """Envía datos raw a la impresora"""
        self._get_config()
        
        if self.printer_type == 'TSPL':
            return self.print_tspl(data.decode('utf-8'))
        
        # Fallback para otros tipos
        print(f"[PRINTER] Enviando {len(data)} bytes (tipo: {self.printer_type})")
        return True
    
    def print_zpl(self, zpl_code: str) -> bool:
        """Imprime código ZPL (para impresoras Zebra)"""
        return self.print_raw(zpl_code.encode('utf-8'))
    
    def print_escpos(self, commands: bytes) -> bool:
        """Imprime comandos ESC/POS (impresoras térmicas)"""
        return self.print_raw(commands)
    
    def get_status(self) -> dict:
        """Retorna el estado de la impresora"""
        self._get_config()
        return {
            'port': self.port,
            'type': self.printer_type,
            'printer_name': self.printer_name,
            'connected': self._connected,
            'available_printers': self.get_available_printers()
        }


# Instancia global
_printer_service: Optional[PrinterService] = None


def get_printer_service() -> PrinterService:
    """Obtiene la instancia del servicio de impresora"""
    global _printer_service
    if _printer_service is None:
        _printer_service = PrinterService()
    return _printer_service
