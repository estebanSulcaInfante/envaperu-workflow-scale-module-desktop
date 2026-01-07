"""
Configuración de logging para el Scale Module.
Escribe logs a archivo y consola para debugging standalone.
"""
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

# Crear directorio de logs si no existe
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# Nombre del archivo de log con fecha
LOG_FILE = os.path.join(LOG_DIR, f'scale_module_{datetime.now().strftime("%Y%m%d")}.log')

# Formato de log
LOG_FORMAT = '%(asctime)s [%(levelname)s] [%(name)s] %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def setup_logger(name: str = 'scale_module') -> logging.Logger:
    """
    Configura y retorna un logger que escribe a archivo y consola.
    
    Args:
        name: Nombre del logger (ej: 'pesaje', 'balanza', 'sticker')
    
    Returns:
        Logger configurado
    """
    logger = logging.getLogger(name)
    
    # Evitar duplicar handlers si ya existe
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    # Handler para archivo (rotativo, max 5MB, mantiene 5 archivos)
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    
    # Handler para consola
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


# Loggers pre-configurados para cada módulo
def get_pesaje_logger():
    return setup_logger('pesaje')

def get_balanza_logger():
    return setup_logger('balanza')

def get_sticker_logger():
    return setup_logger('sticker')

def get_printer_logger():
    return setup_logger('printer')

def get_sync_logger():
    return setup_logger('sync')
