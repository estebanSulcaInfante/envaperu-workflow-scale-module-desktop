import serial
import time
import re
import threading
from typing import Optional, Callable
from flask import current_app
from app.utils.logger import get_balanza_logger

# Logger para este módulo
log = get_balanza_logger()


class ScaleService:
    """Servicio para comunicación con la balanza vía puerto serial"""
    
    def __init__(self, port: str = None, baud_rate: int = None):
        self.port = port or current_app.config.get('SCALE_PORT', 'COM4')
        self.baud_rate = baud_rate or current_app.config.get('SCALE_BAUD_RATE', 9600)
        self.serial_connection: Optional[serial.Serial] = None
        self.is_listening = False
        self._listener_thread: Optional[threading.Thread] = None
        
        # Regex para capturar peso del ticket: "1.     2.1"
        self.pattern = re.compile(r"^\s*\d+\.\s+(\d+\.?\d*)")
    
    def connect(self) -> bool:
        """Establece conexión con la balanza"""
        try:
            log.info(f"Intentando conectar a {self.port} @ {self.baud_rate}...")
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1
            )
            log.info(f"✅ Conexión exitosa en {self.port}")
            return True
        except serial.SerialException as e:
            log.error(f"Error conectando: {e}")
            return False
    
    def disconnect(self):
        """Cierra la conexión con la balanza"""
        if self.serial_connection and self.serial_connection.is_open:
            self.is_listening = False
            self.serial_connection.close()
    
    def read_weight(self) -> Optional[float]:
        """Lee un peso de la balanza (lectura única).
        Raises serial.SerialException si el puerto está desconectado."""
        if not self.serial_connection or not self.serial_connection.is_open:
            raise serial.SerialException("Puerto serial no disponible")
        
        try:
            if self.serial_connection.in_waiting > 0:
                raw_data = self.serial_connection.readline()
                line = raw_data.decode('utf-8', errors='ignore').strip()
                
                log.debug(f"Raw: {raw_data}")
                log.debug(f"Line: '{line}'")
                
                # Ignorar líneas decorativas o vacías
                if "---" in line or "S/N" in line or not line:
                    return None
                
                # Múltiples patrones para diferentes formatos de balanza
                patterns = [
                    r"(\d+\.?\d*)kg\s+NET",           # "2.7kg NET" - formato de tu balanza!
                    r"^\s*\d+\.\s+(\d+\.?\d*)",       # "1.     2.1"
                    r"(\d+\.?\d*)\s*kg",             # "2.1 kg" o "2.1kg"
                    r"^\s*(\d+\.?\d*)\s*$",          # "  2.1  " (solo número)
                    r"[GN]\s*(\d+\.?\d*)",           # "G 2.1" o "N 2.1"
                    r"(\d+\.\d+)",                    # Cualquier decimal
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, line)
                    if match:
                        weight = float(match.group(1))
                        log.info(f"Peso detectado: {weight} kg")
                        return weight
                
                log.warning(f"No se pudo parsear: '{line}'")
                
        except serial.SerialException:
            raise  # Propagar para que _listen_loop la maneje
        except Exception as e:
            log.error(f"Error leyendo peso: {e}")
        
        return None
    
    def start_listening(self, callback: Callable[[float], None], socketio=None):
        """Inicia escucha continua de la balanza en un hilo separado"""
        if self.is_listening:
            return
        
        self.is_listening = True
        self._listener_thread = threading.Thread(
            target=self._listen_loop,
            args=(callback, socketio),
            daemon=True
        )
        self._listener_thread.start()
    
    def stop_listening(self):
        """Detiene la escucha continua"""
        self.is_listening = False
        if self._listener_thread:
            self._listener_thread.join(timeout=2)
    
    def _emit_status(self, socketio, connected: bool):
        """Emite estado de conexión vía WebSocket"""
        if socketio:
            socketio.emit('balanza_status', {
                'connected': connected,
                'listening': self.is_listening,
                'port': self.port
            })
    
    def _listen_loop(self, callback: Callable[[float], None], socketio=None):
        """Loop interno de escucha con auto-reconexión"""
        # Reutilizar conexión existente, solo conectar si no está abierta
        if not self.serial_connection or not self.serial_connection.is_open:
            if not self.connect():
                log.error("No se pudo conectar en listen_loop")
                self._emit_status(socketio, False)
                return
        
        while self.is_listening:
            try:
                weight = self.read_weight()
                if weight is not None:
                    callback(weight)
                time.sleep(0.1)
            except serial.SerialException:
                log.warning("⚠️ Balanza desconectada físicamente")
                self._emit_status(socketio, False)
                
                # Cerrar conexión rota
                try:
                    if self.serial_connection:
                        self.serial_connection.close()
                except Exception:
                    pass
                self.serial_connection = None
                
                # Auto-reconexión
                while self.is_listening:
                    log.info("🔄 Intentando reconectar...")
                    time.sleep(3)
                    if self.connect():
                        log.info("✅ Balanza reconectada")
                        self._emit_status(socketio, True)
                        break
                    log.warning("❌ Reconexión fallida, reintentando en 3s...")
    
    def get_status(self) -> dict:
        """Retorna el estado de la conexión"""
        return {
            'port': self.port,
            'baud_rate': self.baud_rate,
            'connected': self.serial_connection is not None and self.serial_connection.is_open,
            'listening': self.is_listening
        }


# Instancia global del servicio
_scale_service: Optional[ScaleService] = None


def get_scale_service() -> ScaleService:
    """Obtiene la instancia del servicio de balanza"""
    global _scale_service
    if _scale_service is None:
        _scale_service = ScaleService()
    return _scale_service
