from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from pathlib import Path
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


def stop_background_workers(timeout=5):
    stop_background_sync()
    from app.runtime.monitoring_worker import stop_monitoring_worker

    return stop_monitoring_worker(timeout=timeout)


def create_app(config_overrides=None, static_dir=None, start_workers=None):
    app = Flask(__name__, static_folder=None)
    
    # Load config
    app.config.from_object('app.config.Config')
    if config_overrides:
        app.config.update(config_overrides)
    if static_dir is not None:
        app.config['STATIC_DIR'] = str(static_dir)

    from app.utils.logger import configure_logging

    log_dir = app.config.get('STATION_LOG_DIR') or Path(app.instance_path) / 'logs'
    app.config['STATION_LOG_DIR'] = str(Path(log_dir).expanduser().resolve())
    app.config['STATION_LOG_FILE'] = str(
        configure_logging(
            log_dir=app.config['STATION_LOG_DIR'],
            file_level=app.config.get('LOG_FILE_LEVEL', 'INFO'),
            console_level=app.config.get('LOG_CONSOLE_LEVEL', 'INFO'),
            max_bytes=app.config.get('LOG_MAX_BYTES', 10 * 1024 * 1024),
            backup_count=app.config.get('LOG_BACKUP_COUNT', 10),
            rotation_retry_seconds=app.config.get(
                'LOG_ROTATION_RETRY_SECONDS',
                300,
            ),
        )
    )
    
    # Initialize extensions
    db.init_app(app)
    same_origin_only = app.config.get('SAME_ORIGIN_ONLY', False)
    if not same_origin_only:
        CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

    socketio.init_app(
        app,
        cors_allowed_origins=None if same_origin_only else "*",
        async_mode='threading',
    )
    
    # Register blueprints
    from app.routes.pesajes import pesajes_bp
    from app.routes.balanza import balanza_bp
    from app.routes.sync import sync_bp
    from app.routes.orden_trabajo import orden_trabajo_bp
    from app.routes.avance import avance_bp
    from app.routes.ops import ops_bp
    from app.routes.local_capture import local_capture_bp
    from app.runtime.health import health_bp
    from app.runtime.lifecycle import install_runtime_guard
    
    app.register_blueprint(pesajes_bp, url_prefix='/api/pesajes')
    app.register_blueprint(balanza_bp, url_prefix='/api/balanza')
    app.register_blueprint(sync_bp)
    app.register_blueprint(orden_trabajo_bp)
    app.register_blueprint(avance_bp, url_prefix='/api/avance')
    app.register_blueprint(ops_bp, url_prefix='/api/ops')
    app.register_blueprint(local_capture_bp, url_prefix='/api/local/v1')
    app.register_blueprint(health_bp, url_prefix='/api/local/v1/health')
    install_runtime_guard(app)

    if static_dir is not None:
        from app.runtime.static_ui import register_static_ui

        register_static_ui(app, static_dir)
    
    # Validate and migrate local persistence before workers can capture data.
    with app.app_context():
        from app import models as _models  # noqa: F401
        from app.storage.backup import BackupService
        from app.storage.migrations import MigrationManager
        from app.storage.sqlite import configure_sqlite_engine, database_path_from_engine

        engine = db.engine
        if engine.dialect.name == 'sqlite':
            configure_sqlite_engine(engine)
            database_path = database_path_from_engine(engine)
            backup_service = None
            if database_path is not None:
                database_path.parent.mkdir(parents=True, exist_ok=True)
                backup_dir = app.config.get('STATION_BACKUP_DIR')
                if not backup_dir:
                    backup_dir = database_path.parent / 'backups'
                backup_service = BackupService(
                    database_path=database_path,
                    backup_dir=backup_dir,
                    station_id=app.config.get('STATION_ID', 'PESAJE-LOCAL'),
                    retention_count=app.config.get('BACKUP_RETENTION_COUNT', 14),
                )
                app.config['STATION_DATABASE_PATH'] = str(database_path)

            migration_report = MigrationManager(
                engine=engine,
                metadata=db.Model.metadata,
                backup_service=backup_service,
            ).migrate()
            app.config['MIGRATION_REPORT'] = migration_report
            app.config['SCHEMA_VERSION'] = migration_report.current_version
        else:
            db.create_all()

        from app.services.monitoring_service import initialize_station_monitoring

        initialize_station_monitoring(app)
    
    # Start background sync (solo si está habilitado)
    should_start_workers = True if start_workers is None else start_workers
    if should_start_workers:
        if app.config.get('SYNC_ENABLED', True):
            start_background_sync(app)
        if app.config.get('MONITORING_ENABLED', False):
            from app.runtime.monitoring_worker import start_monitoring_worker

            start_monitoring_worker(app)
    
    return app
