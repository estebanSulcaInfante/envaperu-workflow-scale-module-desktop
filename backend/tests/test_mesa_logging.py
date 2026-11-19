import json
import logging
from logging.handlers import RotatingFileHandler

from mesa_logging import (
    configure_mesa_logging,
    get_mesa_logger,
    shutdown_mesa_logging,
)
from mesa_pilot import create_app
from mesa_scale import MesaScaleReader


def _records(path):
    return [
        json.loads(line)
        for log_file in sorted(path.glob("mesa_station.log*"))
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_mesa_logging_is_rotating_persistent_and_does_not_capture_secrets(tmp_path):
    log_dir = tmp_path / "station" / "logs"
    configure_mesa_logging(log_dir, max_bytes=900, backup_count=4, console_level="CRITICAL")

    logger = get_mesa_logger("test")
    logger.info(
        "ignored message",
        extra={
            "mesa_event": "inventory_operation",
            "mesa_fields": {
                "operation": "confirm_unit",
                "correlation_id": "corr-001",
                "http_status": 201,
                "http_outcome": "success",
                "physical_status": "not_verified",
                "qr": "QR-SHOULD-NOT-APPEAR",
                "token": "TOKEN-SHOULD-NOT-APPEAR",
                "body": {"personal": "should-not-appear"},
            },
        },
    )
    for index in range(40):
        logger.info(
            "event",
            extra={
                "mesa_event": "recoverable_failure",
                "mesa_fields": {"operation": "weigh_unit", "error_type": "TransientError", "index": index},
            },
        )
    logger.info(
        "operation",
        extra={
            "mesa_event": "inventory_operation",
            "mesa_fields": {
                "operation": "confirm_unit",
                "http_status": 201,
                "http_outcome": "success",
                "physical_status": "not_verified",
            },
        },
    )

    root_handlers = logging.getLogger("mesa_station").handlers
    assert sum(isinstance(handler, RotatingFileHandler) for handler in root_handlers) == 1
    assert (log_dir / "mesa_station.log.1").exists()
    content = "\n".join(path.read_text(encoding="utf-8") for path in log_dir.glob("mesa_station.log*"))
    assert "QR-SHOULD-NOT-APPEAR" not in content
    assert "TOKEN-SHOULD-NOT-APPEAR" not in content
    assert "should-not-appear" not in content
    records = _records(log_dir)
    assert any(record["event"] == "inventory_operation" for record in records)
    assert any(record.get("physical_status") == "not_verified" for record in records)
    shutdown_mesa_logging()


def test_mesa_http_correlation_and_polling_suppression(tmp_path):
    app = create_app(tmp_path / "data" / "mesa.sqlite3")
    app.config.update(TESTING=True)
    log_dir = tmp_path / "logs"
    with app.test_client() as client:
        response = client.post(
            "/api/mesa/inventario/preetiquetas",
            json={"clave": "logging-test"},
        )
        assert response.status_code == 201
        correlation = response.headers["X-Correlation-ID"]
        assert correlation
        client.get("/api/mesa/balanza")

    records = _records(log_dir)
    operation = next(record for record in records if record["event"] == "inventory_operation")
    assert operation["correlation_id"] == correlation
    assert operation["http_outcome"] == "success"
    assert operation["physical_status"] == "not_verified"
    assert not any(record.get("operation") == "scale_status" for record in records)
    shutdown_mesa_logging()


def test_unconfigured_accura_is_explicit_and_does_not_open_or_start_thread(tmp_path):
    opened = []
    reader = MesaScaleReader(
        None,
        configured=False,
        serial_factory=lambda **kwargs: opened.append(kwargs),
    )

    assert reader.start() is False
    assert reader._thread is None
    assert opened == []
    assert reader.status() == {
        "modo": "accura",
        "disponible": False,
        "base": None,
        "kg": None,
        "mensaje": "Configure el puerto COM de la Accura cuando conecte la balanza.",
    }

    app = create_app(tmp_path / "mesa.sqlite3", scale_reader=reader)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        assert client.get("/api/mesa/balanza").get_json()["disponible"] is False
        response = client.post(
            "/api/mesa/inventario/pesajes",
            json={"codigo": "INV-DEMO-001", "bruto": "1.000", "tara": "0", "clave": "manual"},
        )
        assert response.status_code == 409
    shutdown_mesa_logging()
