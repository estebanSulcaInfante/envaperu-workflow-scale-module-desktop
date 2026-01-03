import serial
import time
import re
import threading
from typing import Optional, Callable
from flask import current_app


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
            self.serial_connection = serial.Serial(
                self.port,
                self.baud_rate,
                timeout=1
            )
            return True
        except serial.SerialException as e:
            print(f"Error conectando a balanza: {e}")
            return False
    
    def disconnect(self):
        """Cierra la conexión con la balanza"""
        if self.serial_connection and self.serial_connection.is_open:
            self.is_listening = False
            self.serial_connection.close()
    
    def read_weight(self) -> Optional[float]:
        """Lee un peso de la balanza (lectura única)"""
        if not self.serial_connection or not self.serial_connection.is_open:
            if not self.connect():
                return None
        
        try:
            if self.serial_connection.in_waiting > 0:
                line = self.serial_connection.readline().decode('utf-8', errors='ignore').strip()
                
                # Ignorar líneas decorativas
                if "---" in line or "S/N" in line or not line:
                    return None
                
                match = self.pattern.search(line)
                if match:
                    return float(match.group(1))
        except Exception as e:
            print(f"Error leyendo peso: {e}")
        
        return None
    
    def start_listening(self, callback: Callable[[float], None]):
        """Inicia escucha continua de la balanza en un hilo separado"""
        if self.is_listening:
            return
        
        self.is_listening = True
        self._listener_thread = threading.Thread(
            target=self._listen_loop,
            args=(callback,),
            daemon=True
        )
        self._listener_thread.start()
    
    def stop_listening(self):
        """Detiene la escucha continua"""
        self.is_listening = False
        if self._listener_thread:
            self._listener_thread.join(timeout=2)
    
    def _listen_loop(self, callback: Callable[[float], None]):
        """Loop interno de escucha"""
        if not self.connect():
            return
        
        while self.is_listening:
            weight = self.read_weight()
            if weight is not None:
                callback(weight)
            time.sleep(0.1)
        
        self.disconnect()
    
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
