"""Privacidad y observabilidad local para la estación 2 (Mesa).

Los eventos son JSONL, persistentes fuera del código instalado y rotativos.
Este módulo deliberadamente no serializa cuerpos HTTP, códigos QR, tokens,
puertos de sesión ni datos personales. El resultado HTTP se conserva separado
de la evidencia física: una respuesta ``2xx`` sólo demuestra que la operación
local fue aceptada o persistida.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator


LOGGER_NAME = "mesa_station"
LOG_FILENAME = "mesa_station.log"
_CONFIG_LOCK = threading.RLock()
_CORRELATION = contextvars.ContextVar("mesa_correlation_id", default=None)
_STARTED = contextvars.ContextVar("mesa_request_started", default=None)
_TOKEN_PATTERN = re.compile(r"(?:token|qr|body|payload|secret|password|cookie|authorization|email|name|phone)", re.I)
_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")

# Fields are intentionally allow-listed. An event can be emitted from a
# future operation without accidentally copying a request object into a log.
_SAFE_FIELDS = {
    "operation", "category", "method", "endpoint", "http_status", "http_outcome",
    "physical_status", "recoverable", "peripheral", "state", "previous_state",
    "component", "error_type", "error_code", "retryable", "duration_ms", "mode",
    "configured", "available", "base", "unit", "stable", "failure_class", "phase",
    "reason", "message_code", "port_configured", "listener_started", "closed",
}


class ResilientMesaRotatingFileHandler(RotatingFileHandler):
    """Continúa escribiendo si Windows bloquea temporalmente el rollover."""

    def __init__(self, *args, rotation_retry_seconds=300, **kwargs):
        super().__init__(*args, **kwargs)
        self.rotation_retry_seconds = max(1, int(rotation_retry_seconds))
        self.next_rotation_attempt = 0.0
        self.rotation_failures = 0

    def emit(self, record):
        try:
            now = time.monotonic()
            if now >= self.next_rotation_attempt and self.shouldRollover(record):
                try:
                    self.doRollover()
                except OSError:
                    self.rotation_failures += 1
                    self.next_rotation_attempt = now + self.rotation_retry_seconds
                    if self.stream is None:
                        self.stream = self._open()
                    # A single concise diagnostic is useful to support and does
                    # not route the exception through logging.handleError.
                    if self.rotation_failures == 1:
                        sys.stderr.write(
                            "[MESA-LOG] Rotacion pospuesta; el archivo esta en uso.\n"
                        )
            logging.FileHandler.emit(self, record)
        except Exception:
            self.handleError(record)


class _JsonFormatter(logging.Formatter):
    converter = time.gmtime

    def format(self, record):
        fields = getattr(record, "mesa_fields", {})
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "station": "mesa",
            "schema_version": 1,
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "mesa_event", "log"),
            "correlation_id": getattr(record, "mesa_correlation_id", None) or get_correlation_id(),
        }
        payload.update({key: fields[key] for key in _SAFE_FIELDS if key in fields})
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _resolve_log_dir(log_dir=None, database_path=None, data_dir=None, config_dir=None) -> Path:
    if log_dir:
        return Path(log_dir).expanduser().resolve()
    candidate = Path(database_path or data_dir or config_dir or Path.cwd()).expanduser().resolve()
    if candidate.suffix:
        candidate = candidate.parent
    if candidate.name.lower() in {"data", "config"}:
        return candidate.parent / "logs"
    return candidate / "logs"


def configure_mesa_logging(
    log_dir=None,
    *,
    database_path=None,
    data_dir=None,
    config_dir=None,
    file_level="INFO",
    console_level="WARNING",
    max_bytes=10 * 1024 * 1024,
    backup_count=10,
    rotation_retry_seconds=300,
) -> Path:
    """Configura el único archivo de diagnóstico de Mesa y devuelve su ruta."""

    directory = _resolve_log_dir(log_dir, database_path, data_dir, config_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LOG_FILENAME
    logger = logging.getLogger(LOGGER_NAME)
    formatter = _JsonFormatter()
    with _CONFIG_LOCK:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        file_handler = ResilientMesaRotatingFileHandler(
            path,
            maxBytes=max(1, int(max_bytes)),
            backupCount=max(0, int(backup_count)),
            encoding="utf-8",
            delay=True,
            rotation_retry_seconds=rotation_retry_seconds,
        )
        file_handler.setLevel(_log_level(file_level, logging.INFO))
        file_handler.setFormatter(formatter)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(_log_level(console_level, logging.WARNING))
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        getattr(log_peripheral_state, "_states", {}).clear()
    return path


def _log_level(value, default):
    if isinstance(value, int):
        return value
    return logging.getLevelNamesMapping().get(str(value).upper(), default)


def get_mesa_logger(component: str | None = None) -> logging.Logger:
    name = LOGGER_NAME if not component else f"{LOGGER_NAME}.{component}"
    logger = logging.getLogger(name)
    logger.setLevel(logging.NOTSET if component else logging.DEBUG)
    logger.propagate = bool(component)
    return logger


def shutdown_mesa_logging() -> None:
    with _CONFIG_LOCK:
        logger = logging.getLogger(LOGGER_NAME)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        getattr(log_peripheral_state, "_states", {}).clear()


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> str:
    value = _CORRELATION.get()
    if value:
        return value
    value = new_correlation_id()
    _CORRELATION.set(value)
    return value


@contextmanager
def bind_correlation(value: str | None = None) -> Iterator[str]:
    candidate = value if isinstance(value, str) and _CORRELATION_PATTERN.fullmatch(value) else new_correlation_id()
    token = _CORRELATION.set(candidate)
    try:
        yield candidate
    finally:
        _CORRELATION.reset(token)


def _safe_fields(fields: dict) -> dict:
    clean = {}
    for key in _SAFE_FIELDS:
        if key not in fields or _TOKEN_PATTERN.search(key):
            continue
        value = fields[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
    return clean


def log_event(event: str, *, level=logging.INFO, correlation_id=None, logger=None, **fields) -> None:
    """Emite un evento con campos allow-list; nunca recibe ni serializa payloads."""

    target = logger or get_mesa_logger()
    safe = _safe_fields(fields)
    cid = correlation_id if isinstance(correlation_id, str) and _CORRELATION_PATTERN.fullmatch(correlation_id) else get_correlation_id()
    target.log(
        level,
        "mesa event",
        extra={"mesa_event": str(event), "mesa_fields": safe, "mesa_correlation_id": cid},
    )


def log_peripheral_state(peripheral: str, state: str, *, logger=None, **fields) -> bool:
    """Registra cambios de estado de periférico sólo cuando cambia el estado."""

    cache = getattr(log_peripheral_state, "_states", None)
    if cache is None:
        cache = log_peripheral_state._states = {}
    key = peripheral
    previous = cache.get(key)
    if previous == state:
        return False
    cache[key] = state
    log_event(
        "peripheral_state_changed",
        logger=logger,
        peripheral=peripheral,
        state=state,
        previous_state=previous,
        **fields,
    )
    return True


def log_startup(*, database_path=None, scale_configured=None, reader_started=None) -> None:
    log_event(
        "mesa_startup",
        category="lifecycle",
        phase="start",
        mode="local",
        port_configured=scale_configured,
        listener_started=reader_started,
    )


def log_shutdown(*, closed=True) -> None:
    log_event("mesa_shutdown", category="lifecycle", phase="stop", closed=closed)


def instrument_flask(app) -> None:
    """Instala correlación y auditoría mínima sin registrar polling ni payloads."""

    from flask import g, request

    ignored = {"state", "scale_status", "inventory_status"}

    @app.before_request
    def _mesa_logging_before_request():
        token = _CORRELATION.set(new_correlation_id())
        g._mesa_correlation_token = token
        g._mesa_request_started = time.monotonic()
        _STARTED.set(g._mesa_request_started)

    @app.after_request
    def _mesa_logging_after_request(response):
        endpoint = request.endpoint or "unknown"
        if endpoint not in ignored and (request.method != "GET" or endpoint not in {"station", "assets"}):
            status = response.status_code
            is_inventory = request.path.startswith("/api/mesa/inventario/")
            is_return = endpoint == "receive"
            log_event(
                "inventory_operation" if is_inventory else "return_operation" if is_return else "http_operation",
                operation=endpoint,
                category=("inventory" if is_inventory else "return" if is_return else "station"),
                method=request.method,
                endpoint=endpoint,
                http_status=status,
                http_outcome="success" if status < 400 else "error",
                physical_status="not_verified",
                recoverable=(400 <= status < 500 or status in (502, 503, 504)),
                duration_ms=round((time.monotonic() - g.get("_mesa_request_started", time.monotonic())) * 1000, 3),
            )
        response.headers["X-Correlation-ID"] = get_correlation_id()
        return response

    @app.teardown_request
    def _mesa_logging_teardown(error):
        if error is not None:
            log_event(
                "request_exception",
                level=logging.ERROR,
                operation=request.endpoint or "unknown",
                error_type=type(error).__name__,
                recoverable=False,
                physical_status="not_verified",
            )
        token = g.pop("_mesa_correlation_token", None)
        if token is not None:
            _CORRELATION.reset(token)


__all__ = [
    "bind_correlation", "configure_mesa_logging", "get_correlation_id",
    "get_mesa_logger", "instrument_flask", "log_event", "log_peripheral_state",
    "log_shutdown", "log_startup", "new_correlation_id", "shutdown_mesa_logging",
    "ResilientMesaRotatingFileHandler",
]
