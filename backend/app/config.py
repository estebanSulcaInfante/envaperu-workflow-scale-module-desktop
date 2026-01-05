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
    PRINTER_TYPE = os.getenv('PRINTER_TYPE', 'ESC_POS')  # ESC_POS, ZPL, CUPS
    
    # API Backend Port
    API_PORT = int(os.getenv('API_PORT', '5050'))
