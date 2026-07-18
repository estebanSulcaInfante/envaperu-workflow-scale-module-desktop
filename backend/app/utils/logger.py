"""Process-wide logging for the local weighing station."""

import logging
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGGER_NAME = "scale_module"
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MANAGED_HANDLER = "_envaperu_station_handler"
_CONFIG_LOCK = threading.RLock()


class ResilientRotatingFileHandler(RotatingFileHandler):
    """Keep appending when Windows temporarily blocks a log rollover."""

    def __init__(self, *args, rotation_retry_seconds=300, **kwargs):
        super().__init__(*args, **kwargs)
        self.rotation_retry_seconds = max(1, int(rotation_retry_seconds))
        self.next_rotation_attempt = 0.0
        self.rotation_failures = 0
        self.last_rotation_error = None

    def emit(self, record):
        try:
            now = time.monotonic()
            should_retry = now >= self.next_rotation_attempt
            if should_retry and self.shouldRollover(record):
                try:
                    self.doRollover()
                    self.last_rotation_error = None
                except PermissionError as exc:
                    self.rotation_failures += 1
                    self.last_rotation_error = str(exc)
                    self.next_rotation_attempt = now + self.rotation_retry_seconds
                    if self.stream is None:
                        self.stream = self._open()
                    sys.stderr.write(
                        "[LOG] Rotacion pospuesta porque Windows mantiene "
                        f"el archivo abierto; reintento en {self.rotation_retry_seconds}s.\n"
                    )

            logging.FileHandler.emit(self, record)
        except Exception:
            self.handleError(record)


def _level(value, default):
    if isinstance(value, int):
        return value
    return logging.getLevelNamesMapping().get(str(value).upper(), default)


def _managed(handler):
    setattr(handler, _MANAGED_HANDLER, True)
    return handler


def _remove_managed_handlers(logger):
    for handler in list(logger.handlers):
        if not getattr(handler, _MANAGED_HANDLER, False):
            continue
        logger.removeHandler(handler)
        handler.close()


def configure_logging(
    log_dir,
    *,
    file_level="INFO",
    console_level="INFO",
    max_bytes=5 * 1024 * 1024,
    backup_count=5,
    rotation_retry_seconds=300,
):
    """Configure one shared file handle for every station component logger."""

    directory = Path(log_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "scale_module.log"
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    formatter.converter = time.gmtime

    with _CONFIG_LOCK:
        module_logger = logging.getLogger(LOGGER_NAME)
        _remove_managed_handlers(module_logger)
        module_logger.setLevel(logging.DEBUG)
        module_logger.propagate = False

        file_handler = _managed(
            ResilientRotatingFileHandler(
                log_path,
                maxBytes=max(1, int(max_bytes)),
                backupCount=max(0, int(backup_count)),
                encoding="utf-8",
                delay=True,
                rotation_retry_seconds=rotation_retry_seconds,
            )
        )
        file_handler.setLevel(_level(file_level, logging.INFO))
        file_handler.setFormatter(formatter)

        console_handler = _managed(logging.StreamHandler())
        console_handler.setLevel(_level(console_level, logging.INFO))
        console_handler.setFormatter(formatter)

        module_logger.addHandler(file_handler)
        module_logger.addHandler(console_handler)

    return log_path


def shutdown_logging():
    with _CONFIG_LOCK:
        _remove_managed_handlers(logging.getLogger(LOGGER_NAME))


def setup_logger(name="scale_module"):
    logger_name = LOGGER_NAME if name == LOGGER_NAME else f"{LOGGER_NAME}.{name}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.NOTSET)
    logger.propagate = logger_name != LOGGER_NAME
    return logger


def get_pesaje_logger():
    return setup_logger("pesaje")


def get_balanza_logger():
    return setup_logger("balanza")


def get_sticker_logger():
    return setup_logger("sticker")


def get_printer_logger():
    return setup_logger("printer")


def get_sync_logger():
    return setup_logger("sync")
