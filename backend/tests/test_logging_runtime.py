import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.services.scale_service import ScaleService
from app.utils.logger import (
    ResilientRotatingFileHandler,
    configure_logging,
    get_balanza_logger,
    get_pesaje_logger,
    shutdown_logging,
)


def _module_file_handlers():
    return [
        handler
        for handler in logging.getLogger("scale_module").handlers
        if isinstance(handler, RotatingFileHandler)
    ]


def test_component_loggers_share_one_rotating_file(tmp_path):
    log_dir = tmp_path / "logs"
    configure_logging(
        log_dir=log_dir,
        file_level="DEBUG",
        console_level="CRITICAL",
        max_bytes=1024,
        backup_count=2,
    )

    balanza = get_balanza_logger()
    pesaje = get_pesaje_logger()
    balanza.info("lectura compartida")
    pesaje.info("captura compartida")

    handlers = _module_file_handlers()
    assert balanza.handlers == []
    assert pesaje.handlers == []
    assert len(handlers) == 1
    assert Path(handlers[0].baseFilename).parent == log_dir
    handlers[0].flush()

    initial_content = (log_dir / "scale_module.log").read_text(encoding="utf-8")
    assert "lectura compartida" in initial_content
    assert "captura compartida" in initial_content

    for index in range(80):
        balanza.info("muestra %03d %s", index, "x" * 80)
    handlers[0].flush()

    assert (log_dir / "scale_module.log.1").exists()
    content = "".join(
        path.read_text(encoding="utf-8")
        for path in log_dir.glob("scale_module.log*")
    )
    assert "muestra 079" in content
    shutdown_logging()


def test_release_app_uses_station_log_directory(tmp_path):
    log_dir = tmp_path / "station-logs"
    app = create_app(
        config_overrides={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": (
                f"sqlite:///{(tmp_path / 'logging.db').as_posix()}"
            ),
            "STATION_LOG_DIR": str(log_dir),
            "LOG_FILE_LEVEL": "INFO",
            "LOG_CONSOLE_LEVEL": "CRITICAL",
        },
        start_workers=False,
    )

    assert app.config["STATION_LOG_DIR"] == str(log_dir)
    handlers = _module_file_handlers()
    assert len(handlers) == 1
    assert Path(handlers[0].baseFilename).parent == log_dir
    shutdown_logging()


def test_locked_rollover_does_not_print_logging_traceback(tmp_path, monkeypatch, capsys):
    log_path = tmp_path / "locked.log"
    handler = ResilientRotatingFileHandler(
        log_path,
        maxBytes=1,
        backupCount=1,
        encoding="utf-8",
        rotation_retry_seconds=300,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr(
        handler,
        "doRollover",
        lambda: (_ for _ in ()).throw(PermissionError("locked")),
    )

    logger = logging.getLogger("test.locked-rollover")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        logger.info("registro conservado")
        logger.info("segundo registro conservado")
        handler.flush()
    finally:
        logger.handlers = []
        handler.close()

    captured = capsys.readouterr()
    assert "--- Logging error ---" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.err.count("[LOG] Rotacion pospuesta") == 1
    content = log_path.read_text(encoding="utf-8")
    assert "registro conservado" in content
    assert "segundo registro conservado" in content


def test_continuous_weight_sample_is_debug_not_info():
    class FakeSerial:
        is_open = True
        in_waiting = 1

        @staticmethod
        def readline():
            return b"     0.0 kg\r\n"

    service = ScaleService(port="COM-TEST", baud_rate=9600)
    service.serial_connection = FakeSerial()

    with patch("app.services.scale_service.log.info") as info_log:
        assert service.read_weight() == 0.0

    assert not any(
        "Peso detectado" in str(call.args[0])
        for call in info_log.call_args_list
    )
