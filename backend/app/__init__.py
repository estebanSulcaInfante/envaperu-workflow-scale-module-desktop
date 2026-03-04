from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
import threading
import time

db = SQLAlchemy()
socketio = SocketIO()

# Background sync thread
_sync_thread = None
_sync_stop_event = threading.Event()


def _background_sync_worker(app):
    """Worker thread que ejecuta sync cada SYNC_INTERVAL_SECONDS."""
    with app.app_context():
        from app.services.sync_service import get_sync_service
        
        interval = app.config.get('SYNC_INTERVAL_SECONDS', 300)
        enabled = app.config.get('SYNC_ENABLED', True)
        
        print(f"[SYNC] Background sync iniciado (cada {interval}s)")
        
        while not _sync_stop_event.is_set() and enabled:
            try:
                service = get_sync_service()
                result = service.sync_pesajes()
                
                if result.get('synced'):
                    print(f"[SYNC] ✅ Sincronizados {len(result['synced'])} pesajes")
                elif result.get('errors'):
                    print(f"[SYNC] ⚠️ Errores: {len(result['errors'])}")
                    
            except Exception as e:
                print(f"[SYNC] ❌ Error: {e}")
            
            # Esperar hasta el próximo ciclo
            _sync_stop_event.wait(interval)
        
        print("[SYNC] Background sync detenido")


def start_background_sync(app):
    """Inicia el hilo de sincronización en background."""
    global _sync_thread
    
    if _sync_thread is not None and _sync_thread.is_alive():
        return  # Ya está corriendo
    
    _sync_stop_event.clear()
    _sync_thread = threading.Thread(
        target=_background_sync_worker,
        args=(app,),
        daemon=True,
        name="SyncWorker"
    )
    _sync_thread.start()


def stop_background_sync():
    """Detiene el hilo de sincronización."""
    global _sync_thread
    _sync_stop_event.set()
    if _sync_thread is not None:
        _sync_thread.join(timeout=5)
        _sync_thread = None


def _run_migrations(database):
    """Add missing columns to existing tables (safe to run multiple times)."""
    migrations = {
        'pesajes': [
            ('peso_unitario_teorico', 'FLOAT'),
            ('operador', 'VARCHAR(100)'),
            ('color', 'VARCHAR(50)'),
            ('pieza_sku', 'VARCHAR(50)'),
            ('pieza_nombre', 'VARCHAR(100)'),
            ('sticker_impreso', 'BOOLEAN DEFAULT 0'),
            ('fecha_impresion', 'DATETIME'),
            ('sincronizado', 'BOOLEAN DEFAULT 0'),
            ('fecha_sincronizacion', 'DATETIME'),
            ('qr_data_original', 'VARCHAR(500)'),
            ('factor_correccion', 'FLOAT DEFAULT 100.0'),
            ('tipo', "VARCHAR(10) DEFAULT 'BOLSA'"),
            ('estado_pucho', 'VARCHAR(15)'),
            ('pucho_origen_id', 'INTEGER REFERENCES pesajes(id)'),
        ],
        'correlativo_cache': [
            ('maquina', 'VARCHAR(50)'),
            ('turno', 'VARCHAR(20)'),
            ('fecha_ot', 'VARCHAR(20)'),
            ('operador', 'VARCHAR(100)'),
            ('color', 'VARCHAR(50)'),
        ],
    }
    for table, columns in migrations.items():
        for col_name, col_type in columns:
            try:
                database.session.execute(
                    database.text(f'ALTER TABLE {table} ADD COLUMN {col_name} {col_type}')
                )
            except Exception:
                pass  # Column already exists
    database.session.commit()


def create_app():
    app = Flask(__name__)
    
    # Load config
    app.config.from_object('app.config.Config')
    
    # Initialize extensions
    db.init_app(app)
    # Configure CORS - Permissive for dev
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    # Initialize SocketIO
    socketio.init_app(app, cors_allowed_origins="*", async_mode='threading')
    
    # Register blueprints
    from app.routes.pesajes import pesajes_bp
    from app.routes.balanza import balanza_bp
    from app.routes.sync import sync_bp
    from app.routes.rdp import rdp_bp
    from app.routes.avance import avance_bp
    
    app.register_blueprint(pesajes_bp, url_prefix='/api/pesajes')
    app.register_blueprint(balanza_bp, url_prefix='/api/balanza')
    app.register_blueprint(sync_bp)
    app.register_blueprint(rdp_bp)
    app.register_blueprint(avance_bp, url_prefix='/api/avance')
    
    # Create tables
    with app.app_context():
        db.create_all()
        # Migrate: add new columns to correlativo_cache if they don't exist
        _run_migrations(db)
    
    # Start background sync (solo si está habilitado)
    if app.config.get('SYNC_ENABLED', True):
        start_background_sync(app)
    
    return app
