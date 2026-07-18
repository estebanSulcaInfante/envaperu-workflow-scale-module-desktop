import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuración de la aplicación"""
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
    
    # Local station persistence. Release overrides this with ProgramData.
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'sqlite:///pesajes.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    BACKUP_RETENTION_COUNT = int(os.getenv('BACKUP_RETENTION_COUNT', '14'))
    MAX_CAPTURE_WEIGHT_KG = float(os.getenv('MAX_CAPTURE_WEIGHT_KG', '1000'))
    LEGACY_MIGRATION_MODE = os.getenv('LEGACY_MIGRATION_MODE', 'False').lower() == 'true'
    STATION_CODE = os.getenv('STATION_CODE', os.getenv('STATION_ID', 'PESAJE-PLANTA-01'))
    STATION_UUID = os.getenv('STATION_UUID')
    STATION_MODE = os.getenv('STATION_MODE', 'MONITORED_LEGACY')
    STATION_APP_VERSION = os.getenv('STATION_APP_VERSION', '1.1.0-pilot')
    TIMEZONE = os.getenv('TIMEZONE', 'America/Lima')
    
    # Scale (Balanza)
    SCALE_PORT = os.getenv('SCALE_PORT', 'COM4')
    SCALE_BAUD_RATE = int(os.getenv('SCALE_BAUD_RATE', '9600'))
    
    # Printer (Impresora)
    PRINTER_PORT = os.getenv('PRINTER_PORT', 'COM3')
    PRINTER_TYPE = os.getenv('PRINTER_TYPE', 'TSPL')  # TSPL, ESC_POS, ZPL
    PRINTER_NAME = os.getenv('PRINTER_NAME', None)  # Nombre Windows (ej: "TSC TE200")
    
    # API Backend Port
    API_PORT = int(os.getenv('API_PORT', '5050'))
    
    # Sync con Backend Central
    CENTRAL_API_URL = os.getenv('CENTRAL_API_URL', 'http://localhost:5000/api')
    CENTRAL_ORIGIN = os.getenv('CENTRAL_ORIGIN', 'http://localhost:5000')
    ALLOW_INSECURE_CENTRAL = os.getenv(
        'ALLOW_INSECURE_CENTRAL',
        'false',
    ).lower() == 'true'
    SYNC_INTERVAL_SECONDS = int(os.getenv('SYNC_INTERVAL_SECONDS', '300'))
    SYNC_ENABLED = os.getenv('SYNC_ENABLED', 'true').lower() == 'true'
    MONITORING_ENABLED = os.getenv('MONITORING_ENABLED', 'true').lower() == 'true'
    HEARTBEAT_SECONDS = int(os.getenv('HEARTBEAT_SECONDS', '30'))
    PRODUCTION_PROGRESS_DAYS = int(os.getenv('PRODUCTION_PROGRESS_DAYS', '31'))

    # Runtime logs. Release places STATION_LOG_DIR under ProgramData.
    STATION_LOG_DIR = os.getenv('STATION_LOG_DIR')
    LOG_FILE_LEVEL = os.getenv('LOG_FILE_LEVEL', 'INFO')
    LOG_CONSOLE_LEVEL = os.getenv('LOG_CONSOLE_LEVEL', 'INFO')
    LOG_MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', str(10 * 1024 * 1024)))
    LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', '10'))
    LOG_ROTATION_RETRY_SECONDS = int(
        os.getenv('LOG_ROTATION_RETRY_SECONDS', '300')
    )

