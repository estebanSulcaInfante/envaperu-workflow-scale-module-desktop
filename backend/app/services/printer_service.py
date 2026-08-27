"""
Servicio de impresión de etiquetas/stickers.
Soporta impresoras TSC (TSPL), Zebra (ZPL) y térmicas (ESC/POS).
"""
from dataclasses import asdict, dataclass
from typing import Optional, List
import threading
import time
from flask import current_app


@dataclass(frozen=True)
class PrinterEmissionResult:
    """Resultado con suficiente evidencia para decidir si es seguro reintentar."""

    ACCEPTED = "ACCEPTED"
    NOT_EMITTED = "NOT_EMITTED"
    UNCERTAIN = "UNCERTAIN"

    status: str
    expected_bytes: int
    bytes_written: Optional[int] = None
    document_started: bool = False
    write_attempted: bool = False
    simulated: bool = False
    job_id: Optional[int] = None
    error: Optional[str] = None

    def __bool__(self):
        return self.status == self.ACCEPTED

    def to_dict(self):
        return asdict(self)


class PrinterService:
    """Servicio para comunicación con la impresora de etiquetas"""
    
    def __init__(self, port: str = None, printer_type: str = None, printer_name: str = None):
        self.port = port
        self.printer_type = printer_type
        self.printer_name = printer_name  # Nombre de impresora Windows
        self._connected = False
        self._print_condition = threading.Condition()
        self._active_prints = 0
        self._accepting_prints = True

    def _begin_print(self) -> bool:
        with self._print_condition:
            if not self._accepting_prints:
                return False
            self._active_prints += 1
            return True

    def _end_print(self):
        with self._print_condition:
            self._active_prints -= 1
            self._print_condition.notify_all()
    
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

    def shutdown(self, timeout=5) -> bool:
        """Deja de aceptar trabajos y espera los ya enviados al spooler."""
        deadline = time.monotonic() + timeout
        with self._print_condition:
            self._accepting_prints = False
            while self._active_prints:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._print_condition.wait(timeout=remaining)
            drained = self._active_prints == 0
        self.disconnect()
        return drained
    
    def print_tspl_result(self, tspl_code: str) -> PrinterEmissionResult:
        """Envía TSPL y conserva la frontera entre fallo seguro e incierto.

        Una vez que ``StartDocPrinter`` fue aceptado, cualquier fallo posterior
        se clasifica como incierto. En particular, una escritura parcial nunca
        puede habilitar una reimpresión automática.
        """
        payload = tspl_code.encode('utf-8')
        expected_bytes = len(payload)
        try:
            if current_app.config.get('SIMULATE_PRINTER', False):
                print(
                    f"[PRINTER] Simulacion local: {expected_bytes} bytes TSPL "
                    "aceptados sin enviar al spooler"
                )
                return PrinterEmissionResult(
                    status=PrinterEmissionResult.ACCEPTED,
                    expected_bytes=expected_bytes,
                    bytes_written=expected_bytes,
                    simulated=True,
                )
        except RuntimeError:
            pass

        if not self._begin_print():
            return PrinterEmissionResult(
                status=PrinterEmissionResult.NOT_EMITTED,
                expected_bytes=expected_bytes,
                error="El servicio de impresión se está deteniendo",
            )

        handle = None
        document_started = False
        page_started = False
        write_attempted = False
        bytes_written = None
        job_id = None
        try:
            try:
                import win32print
            except ImportError as exc:
                print("[PRINTER] win32print no disponible; no se emitió el trabajo")
                return PrinterEmissionResult(
                    status=PrinterEmissionResult.NOT_EMITTED,
                    expected_bytes=expected_bytes,
                    error=str(exc) or "win32print no disponible",
                )

            try:
                if not self._connected:
                    self.connect()
                if not self.printer_name:
                    raise RuntimeError("No se encontró impresora TSC")
                handle = win32print.OpenPrinter(self.printer_name)
            except Exception as exc:
                print(f"[PRINTER] ❌ Fallo previo a emisión: {exc}")
                return PrinterEmissionResult(
                    status=PrinterEmissionResult.NOT_EMITTED,
                    expected_bytes=expected_bytes,
                    error=str(exc)[:500],
                )

            try:
                job_id = win32print.StartDocPrinter(
                    handle, 1, ("Label", None, "RAW")
                )
                document_started = True
                win32print.StartPagePrinter(handle)
                page_started = True
                write_attempted = True
                bytes_written = win32print.WritePrinter(handle, payload)
                if bytes_written != expected_bytes:
                    raise IOError(
                        "Escritura RAW incompleta: "
                        f"{bytes_written!r} de {expected_bytes} bytes"
                    )
                win32print.EndPagePrinter(handle)
                page_started = False
                win32print.EndDocPrinter(handle)
                document_started = False
            except Exception as exc:
                status = (
                    PrinterEmissionResult.UNCERTAIN
                    if document_started
                    else PrinterEmissionResult.NOT_EMITTED
                )
                qualifier = (
                    "Emisión incierta"
                    if status == PrinterEmissionResult.UNCERTAIN
                    else "Fallo previo a emisión"
                )
                print(f"[PRINTER] ⚠️ {qualifier}: {exc}")
                return PrinterEmissionResult(
                    status=status,
                    expected_bytes=expected_bytes,
                    bytes_written=bytes_written,
                    document_started=document_started,
                    write_attempted=write_attempted,
                    job_id=job_id,
                    error=str(exc)[:500],
                )

            print(f"[PRINTER] ✅ Sticker aceptado por {self.printer_name}")
            return PrinterEmissionResult(
                status=PrinterEmissionResult.ACCEPTED,
                expected_bytes=expected_bytes,
                bytes_written=bytes_written,
                document_started=True,
                write_attempted=True,
                job_id=job_id,
            )
        finally:
            if handle is not None:
                # El cleanup puede terminar entregando al spooler bytes que ya
                # habían sido aceptados. Por eso nunca vuelve seguro un fallo.
                if page_started:
                    try:
                        win32print.EndPagePrinter(handle)
                    except Exception as exc:
                        print(f"[PRINTER] Error cerrando página RAW: {exc}")
                if document_started:
                    try:
                        win32print.EndDocPrinter(handle)
                    except Exception as exc:
                        print(f"[PRINTER] Error cerrando documento RAW: {exc}")
                try:
                    win32print.ClosePrinter(handle)
                except Exception as exc:
                    print(f"[PRINTER] Error cerrando impresora: {exc}")
            self._end_print()

    def print_tspl(self, tspl_code: str) -> bool:
        """Compatibilidad legacy; SCM consume ``print_tspl_result``."""
        return bool(self.print_tspl_result(tspl_code))
    
    def print_raw(self, data: bytes) -> bool:
        """Envía datos raw a la impresora"""
        self._get_config()
        
        if self.printer_type == 'TSPL':
            return self.print_tspl(data.decode('utf-8'))

        if not self._begin_print():
            return False
        try:
            # Fallback para otros tipos
            print(f"[PRINTER] Enviando {len(data)} bytes (tipo: {self.printer_type})")
            return True
        finally:
            self._end_print()
    
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


def shutdown_printer_service(timeout=5) -> bool:
    if _printer_service is None:
        return True
    return _printer_service.shutdown(timeout=timeout)
