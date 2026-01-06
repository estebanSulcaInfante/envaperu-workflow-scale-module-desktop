import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuración de la aplicación"""
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
    
    # Database (SQLite default for testing, PostgreSQL for production)
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'sqlite:///pesajes.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
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
    SYNC_INTERVAL_SECONDS = int(os.getenv('SYNC_INTERVAL_SECONDS', '300'))
    SYNC_ENABLED = os.getenv('SYNC_ENABLED', 'true').lower() == 'true'

