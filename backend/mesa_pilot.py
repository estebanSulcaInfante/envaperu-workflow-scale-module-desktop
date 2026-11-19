"""Persistencia local para el piloto de la mesa de pesaje.

Este módulo es deliberadamente independiente del backend SCM existente. No
llama a Central, no toca Kardex y no usa hardware: solo conserva el estado del
recorrido de demo en un archivo SQLite indicado por ``create_app``.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import qrcode
from flask import Flask, Response, g, jsonify, request
from qrcode.image.svg import SvgImage

from mesa_logging import configure_mesa_logging, instrument_flask, log_event


_SCHEMA = """
CREATE TABLE IF NOT EXISTS units (
    code TEXT PRIMARY KEY,
    piece TEXT NOT NULL,
    color TEXT NOT NULL,
    lot TEXT,
    status TEXT NOT NULL CHECK (status IN ('available', 'reserved', 'pending', 'received')),
    origins_json TEXT NOT NULL DEFAULT '[]',
    origin_key TEXT UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    code TEXT PRIMARY KEY REFERENCES units(code),
    request_id TEXT NOT NULL UNIQUE,
    net_kg TEXT NOT NULL,
    scale_token TEXT,
    scale_base TEXT,
    scale_kg TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_units_status ON units(status);
CREATE TABLE IF NOT EXISTS mesa_scale_captures (
    token TEXT PRIMARY KEY,
    codigo TEXT NOT NULL,
    kg TEXT NOT NULL,
    base TEXT NOT NULL CHECK (base IN ('NT', 'GS')),
    captured_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
"""

_SEED_UNITS = (
    ("OFDEMO-OT101-M001", "TAPA", "AZUL", "LOTE-A"),
    ("OFDEMO-OT101-M002", "TAPA", "AZUL", "LOTE-B"),
    ("OFDEMO-OT101-M003", "TAPA", "AZUL", None),
    ("OFDEMO-OT101-M004", "ASA", "BLANCA", "LOTE-C"),
    ("OFDEMO-OT101-M005", "CUERPO", "ROJO", "LOTE-D"),
    ("OFDEMO-OT101-M006", "ASA", "BLANCA", None),
)

class MesaPilotError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_error(message: str, status_code: int):
    return jsonify(error=message), status_code


def _connect(app: Flask) -> sqlite3.Connection:
    database = app.config["MESA_DB_PATH"]
    connection = sqlite3.connect(database, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _init_database(app: Flask) -> None:
    database = app.config["MESA_DB_PATH"]
    if database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(app)
    try:
        connection.executescript(_SCHEMA)
        receipt_columns = {row["name"] for row in connection.execute("PRAGMA table_info(receipts)")}
        for column in ("scale_token", "scale_base", "scale_kg"):
            if column not in receipt_columns:
                connection.execute(f"ALTER TABLE receipts ADD COLUMN {column} TEXT")
        if not app.extensions.get("mesa_central") and connection.execute("SELECT COUNT(*) FROM units").fetchone()[0] == 0:
            created_at = _utc_now()
            connection.executemany(
                """
                INSERT INTO units
                    (code, piece, color, lot, status, origins_json, origin_key, created_at)
                VALUES (?, ?, ?, ?, 'available', '[]', NULL, ?)
                """,
                [(*unit, created_at) for unit in _SEED_UNITS],
            )
    finally:
        connection.close()


def _db() -> sqlite3.Connection:
    if "mesa_db" not in g:
        g.mesa_db = _connect(g.mesa_app)
    return g.mesa_db


def _row_to_unit(row: sqlite3.Row) -> dict:
    return {
        "code": row["code"],
        "piece": row["piece"],
        "color": row["color"],
        "lot": row["lot"],
        "status": row["status"],
        "origins": json.loads(row["origins_json"]),
    }


def _origin_key(codes: list[str]) -> str:
    return json.dumps(sorted(codes), separators=(",", ":"))


def _payload() -> dict:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise MesaPilotError("El cuerpo debe ser un objeto JSON", 400)
    return value


def _require_local_origin() -> None:
    origin = request.headers.get("Origin")
    if not origin:
        return
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise MesaPilotError("Solo se permiten escrituras desde el equipo local", 403)


def _parse_codes(payload: dict) -> list[str]:
    codes = payload.get("codes")
    if not isinstance(codes, list) or len(codes) < 2:
        raise MesaPilotError("Se requieren al menos dos códigos", 422)
    if any(not isinstance(code, str) or not code.strip() for code in codes):
        raise MesaPilotError("Cada código debe ser texto no vacío", 422)
    normalized = [code.strip() for code in codes]
    if len(set(normalized)) != len(normalized):
        raise MesaPilotError("Los códigos de la unión deben ser únicos", 422)
    return normalized


def _parse_net_kg(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MesaPilotError("net_kg debe ser un texto con peso positivo", 422)
    value = value.strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,3})?", value):
        raise MesaPilotError("net_kg debe usar decimal llano con hasta tres decimales", 422)
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise MesaPilotError("net_kg no es un número válido", 422)
    if not number.is_finite() or number <= 0:
        raise MesaPilotError("net_kg debe ser finito y mayor que cero", 422)
    if -number.as_tuple().exponent > 3:
        raise MesaPilotError("net_kg admite como máximo tres decimales", 422)
    return format(number, ".3f")


def _parse_request_id(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MesaPilotError("request_id debe ser texto no vacío", 422)
    return value.strip()


def create_app(db_path=None, scale_reader=None, log_dir=None, central=None) -> Flask:
    """Crea la aplicación de mesa usando únicamente una base SQLite local."""

    app = Flask(__name__)
    database = Path(db_path or Path.cwd() / "mesa_pilot.sqlite3")
    app.config["MESA_DB_PATH"] = str(database)
    app.config["MESA_LOG_FILE"] = str(
        configure_mesa_logging(log_dir, database_path=database)
    )
    app.config["MESA_LOG_DIR"] = str(Path(app.config["MESA_LOG_FILE"]).parent)
    app.extensions["mesa_scale_reader"] = scale_reader
    app.extensions["mesa_central"] = central

    @app.before_request
    def protect_mutations_from_external_origins():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            _require_local_origin()

    @app.before_request
    def attach_app_to_request_context():
        g.mesa_app = app

    @app.teardown_appcontext
    def close_db(_error=None):
        connection = g.pop("mesa_db", None)
        if connection is not None:
            connection.close()

    @app.errorhandler(MesaPilotError)
    def handle_mesa_error(error):
        return _json_error(error.message, error.status_code)

    @app.errorhandler(404)
    def handle_not_found(_error):
        return _json_error("Recurso no encontrado", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return _json_error("Método no permitido", 405)

    # Correlaciona operaciones sin serializar cuerpos, QR ni tokens. El
    # endpoint de polling de balanza queda fuera para evitar inundar el log.
    instrument_flask(app)

    @app.get("/api/mesa/state")
    def state():
        connection = _db()
        units = connection.execute(
            "SELECT code, piece, color, lot, status, origins_json FROM units ORDER BY code"
        ).fetchall()
        receipts = connection.execute(
            "SELECT code, net_kg, created_at FROM receipts ORDER BY created_at, code"
        ).fetchall()
        return jsonify(
            units=[_row_to_unit(unit) for unit in units],
            receipts=[dict(receipt) for receipt in receipts],
        )

    @app.get("/api/mesa/balanza")
    def scale_status():
        reader = app.extensions.get("mesa_scale_reader")
        if reader is None:
            return jsonify(
                modo="manual", disponible=True, base=None, kg=None,
                mensaje="Modo manual; no hay lector Accura configurado.",
            )
        return jsonify(reader.status())

    @app.post("/api/mesa/balanza/capturas")
    @app.post("/api/mesa/balanza/captura")
    def freeze_scale_capture():
        payload = _payload()
        code = payload.get("codigo")
        if not isinstance(code, str) or not code.strip():
            raise MesaPilotError("codigo debe ser texto no vacío", 422)
        reader = app.extensions.get("mesa_scale_reader")
        if reader is None:
            raise MesaPilotError("No hay balanza Accura configurada", 409)
        code = code.strip()
        connection = _db()
        known = central is not None or connection.execute("SELECT 1 FROM units WHERE code = ?", (code,)).fetchone()
        if not known:
            try:
                known = connection.execute("SELECT 1 FROM inv_mangas WHERE codigo = ?", (code,)).fetchone()
            except sqlite3.OperationalError:
                known = None
        if known is None:
            raise MesaPilotError(f"No existe la manga {code}", 404)
        try:
            capture = reader.snapshot_for(code)
        except ValueError as error:
            raise MesaPilotError(str(error), 409)
        connection.execute(
            "INSERT INTO mesa_scale_captures (token, codigo, kg, base, captured_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                capture["token"], code, capture["kg"], capture["base"],
                capture["captured_at"].isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                datetime.fromtimestamp(capture["expires_at"], timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            ),
        )
        return jsonify(
            token=capture["token"], codigo=code, kg=capture["kg"], base=capture["base"],
            captured_at=capture["captured_at"].isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            expires_at=datetime.fromtimestamp(capture["expires_at"], timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        ), 201

    @app.post("/api/mesa/unions")
    def create_union():
        codes = _parse_codes(_payload())
        connection = _db()
        origin_key = _origin_key(codes)
        connection.execute("BEGIN IMMEDIATE")
        try:
            existing = connection.execute(
                "SELECT code FROM units WHERE origin_key = ?", (origin_key,)
            ).fetchone()
            if existing is not None:
                connection.commit()
                return jsonify(code=existing["code"]), 200

            placeholders = ",".join("?" for _ in codes)
            rows = connection.execute(
                f"SELECT * FROM units WHERE code IN ({placeholders})", codes
            ).fetchall()
            found = {row["code"]: row for row in rows}
            missing = next((code for code in codes if code not in found), None)
            if missing:
                raise MesaPilotError(f"No existe la manga {missing}", 404)
            if any(row["status"] != "available" for row in rows):
                raise MesaPilotError("Todas las mangas deben estar disponibles", 409)
            if len({(row["piece"], row["color"]) for row in rows}) != 1:
                raise MesaPilotError("Las mangas deben compartir pieza y color", 409)

            first = rows[0]
            lots = {row["lot"] for row in rows}
            lot = next(iter(lots)) if len(lots) == 1 else None
            next_number = connection.execute(
                "SELECT COALESCE(MAX(CAST(substr(code, 7) AS INTEGER)), 0) "
                "FROM units WHERE code GLOB 'UNION-[0-9]*'"
            ).fetchone()[0] + 1
            code = f"UNION-{next_number:03d}"
            created_at = _utc_now()
            connection.execute(
                """
                INSERT INTO units
                    (code, piece, color, lot, status, origins_json, origin_key, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (code, first["piece"], first["color"], lot, json.dumps(sorted(codes)), origin_key, created_at),
            )
            connection.executemany(
                "UPDATE units SET status = 'reserved' WHERE code = ?",
                [(code,) for code in codes],
            )
            connection.commit()
            return jsonify(code=code), 201
        except Exception:
            connection.rollback()
            raise

    @app.post("/api/mesa/receive")
    def receive():
        payload = _payload()
        code = payload.get("code")
        if not isinstance(code, str) or not code.strip():
            raise MesaPilotError("code debe ser texto no vacío", 422)
        code = code.strip()
        request_id = _parse_request_id(payload.get("request_id"))
        reader = app.extensions.get("mesa_scale_reader")
        scale_token = payload.get("scale_token")
        connection = _db()
        connection.execute("BEGIN IMMEDIATE")
        try:
            previous = connection.execute(
                "SELECT code, net_kg, scale_token, created_at FROM receipts WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if previous is not None:
                if previous["code"] != code:
                    raise MesaPilotError("request_id ya fue usado con otra recepción", 409)
                if reader is None:
                    same_intent = _parse_net_kg(payload.get("net_kg")) == previous["net_kg"]
                else:
                    same_intent = (
                        isinstance(scale_token, str)
                        and scale_token.strip() == previous["scale_token"]
                        and ("net_kg" not in payload or _parse_net_kg(payload["net_kg"]) == previous["net_kg"])
                    )
                if same_intent:
                    connection.commit()
                    return jsonify(
                        code=previous["code"], net_kg=previous["net_kg"], created_at=previous["created_at"]
                    ), 200
                raise MesaPilotError("request_id ya fue usado con otra intención de captura", 409)

            if reader is not None:
                if not isinstance(scale_token, str) or not scale_token.strip():
                    raise MesaPilotError("La recepción física requiere una captura de balanza", 409)
                from mesa_scale import consume_capture, validate_capture, ScaleCaptureError
                try:
                    capture = validate_capture(connection, scale_token.strip(), code)
                except ScaleCaptureError as error:
                    raise MesaPilotError(str(error), 409)
                if capture["base"] != "NT":
                    raise MesaPilotError("El retorno requiere una lectura Accura de base NT", 409)
                net_kg = _parse_net_kg(payload.get("net_kg", capture["kg"]))
                if Decimal(net_kg) != Decimal(str(capture["kg"])):
                    raise MesaPilotError("El peso informado no coincide con la captura de balanza", 409)
            else:
                net_kg = _parse_net_kg(payload.get("net_kg"))

            unit = connection.execute("SELECT * FROM units WHERE code = ?", (code,)).fetchone()
            if unit is None:
                raise MesaPilotError(f"No existe la unidad {code}", 404)
            if unit["status"] not in {"available", "pending"}:
                raise MesaPilotError("La unidad no está disponible para recepción", 409)

            created_at = _utc_now()
            connection.execute(
                "INSERT INTO receipts (code, request_id, net_kg, scale_token, scale_base, scale_kg, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    code, request_id, net_kg,
                    scale_token.strip() if reader is not None else None,
                    capture["base"] if reader is not None else None,
                    capture["kg"] if reader is not None else None,
                    created_at,
                ),
            )
            connection.execute("UPDATE units SET status = 'received' WHERE code = ?", (code,))
            origins = json.loads(unit["origins_json"])
            if origins:
                placeholders = ",".join("?" for _ in origins)
                connection.execute(
                    f"UPDATE units SET status = 'received' WHERE code IN ({placeholders})", origins
                )
            if reader is not None:
                consume_capture(connection, scale_token.strip())
            connection.commit()
            return jsonify(code=code, net_kg=net_kg, created_at=created_at), 201
        except Exception:
            connection.rollback()
            raise

    @app.get("/api/mesa/qr/<code>.svg")
    def qr(code):
        unit = central.label(code, "retornos") if central else _db().execute("SELECT code FROM units WHERE code = ?", (code,)).fetchone()
        if unit is None:
            raise MesaPilotError(f"No existe la unidad {code}", 404)
        # Mantener el quiet zone estándar de cuatro módulos para escaneo físico.
        qr_code = qrcode.QRCode(border=4, box_size=8)
        qr_code.add_data(code)
        qr_code.make(fit=True)
        image = qr_code.make_image(image_factory=SvgImage)
        output = io.BytesIO()
        image.save(output)
        return Response(output.getvalue(), mimetype="image/svg+xml")

    _init_database(app)
    from mesa_inventory import register_inventory_routes

    register_inventory_routes(app)
    return app


__all__ = ["create_app"]
