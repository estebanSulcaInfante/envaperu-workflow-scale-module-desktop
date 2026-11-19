"""Inventario físico local del piloto de mesa.

Las tablas ``inv_*`` son un sublibro aislado de la simulación. Las identidades
de ``mesa_pilot`` se proyectan para consulta, pero una operación de retorno no
crea movimientos de inventario automáticamente.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import current_app, g, has_app_context, jsonify, request
from mesa_scale import ScaleCaptureError, consume_capture, validate_capture


ZONES = (
    ("Z-ALMACEN-PIEZAS", "Almacén de piezas general"),
    ("Z-ALMACEN-ARMADO-3P", "Almacén de armado – 3.er piso"),
    ("Z-ALMACEN-LLANTAS-3P", "Almacén de llantas – 3.er piso"),
    ("Z-ALMACEN-ARMADO-4P", "Almacén de armado – 4.º piso"),
)
ARTICLES = (
    ("ART-TAPA-AZUL", "Tapa", "Azul"),
    ("ART-ASA-BLANCA", "Asa", "Blanca"),
    ("ART-CUERPO-ROJO", "Cuerpo", "Rojo"),
)
BASE = "/api/mesa/inventario"
_GRAMS = re.compile(r"^[0-9]+(?:\.[0-9]{1,3})?$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_zonas (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS inv_articulos (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    color TEXT NOT NULL,
    UNIQUE(nombre, color)
);
CREATE TABLE IF NOT EXISTS inv_mangas (
    codigo TEXT PRIMARY KEY,
    articulo_id TEXT NOT NULL,
    zona_id TEXT,
    estado TEXT NOT NULL,
    bruto TEXT,
    tara TEXT,
    neto TEXT,
    baja_causa TEXT,
    baja_movimiento_id INTEGER,
    baja_ref TEXT,
    custodia_id TEXT,
    origen TEXT NOT NULL DEFAULT 'INVENTARIO',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inv_sesiones (
    id TEXT PRIMARY KEY,
    zona_id TEXT NOT NULL,
    estado TEXT NOT NULL,
    clave TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE TABLE IF NOT EXISTS inv_lecturas (
    sesion_id TEXT NOT NULL,
    codigo TEXT NOT NULL,
    zona_anterior TEXT,
    estado_anterior TEXT,
    bruto_anterior TEXT,
    tara_anterior TEXT,
    neto_anterior TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (sesion_id, codigo)
);
CREATE TABLE IF NOT EXISTS inv_preetiquetas (
    codigo TEXT PRIMARY KEY,
    clave TEXT NOT NULL UNIQUE,
    estado TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inv_pendientes (
    codigo TEXT PRIMARY KEY,
    articulo_id TEXT NOT NULL,
    zona_id TEXT NOT NULL,
    estado TEXT NOT NULL,
    bruto TEXT,
    tara TEXT,
    neto TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inv_pesajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL,
    bruto TEXT NOT NULL,
    tara TEXT NOT NULL,
    neto TEXT NOT NULL,
    clave TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inv_movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL,
    tipo TEXT NOT NULL,
    delta TEXT NOT NULL,
    motivo TEXT NOT NULL,
    clave TEXT NOT NULL UNIQUE,
    vinculo_baja INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inv_requests (
    clave TEXT PRIMARY KEY,
    operacion TEXT NOT NULL,
    fingerprint TEXT,
    respuesta_json TEXT NOT NULL,
    status_code INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS inv_revisiones (
    token TEXT PRIMARY KEY,
    codigo TEXT NOT NULL,
    estado TEXT NOT NULL,
    neto TEXT,
    created_at TEXT NOT NULL,
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS inv_fixture_bajas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    causa TEXT NOT NULL,
    delta TEXT NOT NULL,
    referencia TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inv_mangas_estado ON inv_mangas(estado);
CREATE INDEX IF NOT EXISTS idx_inv_movimientos_codigo ON inv_movimientos(codigo);
"""

_FIXTURES = (
    ("INV-DEMO-001", "ART-TAPA-AZUL", "Z-ALMACEN-PIEZAS", "DISPONIBLE", "1.500", None),
    ("INV-DEMO-002", "ART-ASA-BLANCA", "Z-ALMACEN-PIEZAS", "DISPONIBLE", "0.900", None),
    ("INV-DEMO-FALTANTE", "ART-TAPA-AZUL", "Z-ALMACEN-PIEZAS", "BAJA_COMPROBADA", "2.000", "FALTANTE"),
    ("INV-DEMO-NO-RECUPERABLE", "ART-ASA-BLANCA", "Z-ALMACEN-ARMADO-3P", "BAJA_NO_RECUPERABLE", "0.850", "NO_RECUPERABLE"),
)


class InventoryError(Exception):
    def __init__(self, message: str, status_code: int, **extra):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.extra = extra


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _connect_path(db_path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path), timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _app_path(app=None, db_path=None):
    if db_path is not None:
        return str(db_path)
    if app is not None:
        return app.config["MESA_DB_PATH"]
    return str(Path.cwd() / "mesa_pilot.sqlite3")


def _db():
    if "inv_db" not in g:
        app = g.get("mesa_app") or current_app
        g.inv_db = _connect_path(_app_path(app))
    return g.inv_db


def _json_error(error: InventoryError):
    return jsonify(error=error.message, **error.extra), error.status_code


def _payload() -> dict:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise InventoryError("El cuerpo debe ser un objeto JSON", 400)
    return value


def _text(payload: dict, key: str, *, required=True) -> str | None:
    value = payload.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"{key} debe ser texto no vacío", 422)
    return value.strip()


def _begin(connection):
    connection.execute("BEGIN IMMEDIATE")


def _fingerprint(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _request_replay(connection, clave: str, operacion: str, fingerprint: str | None = None):
    row = connection.execute("SELECT * FROM inv_requests WHERE clave = ?", (clave,)).fetchone()
    if row is None:
        return None
    if row["operacion"] != operacion:
        raise InventoryError("clave ya usada para otra operación", 409)
    if fingerprint and row["fingerprint"] and row["fingerprint"] != fingerprint:
        raise InventoryError("clave repetida con contenido diferente", 409)
    # A replay acknowledges an already applied operation rather than creating
    # another resource, even when the original response was 201.
    return json.loads(row["respuesta_json"]), 200


def _save_request(connection, clave: str, operacion: str, response: dict, status_code: int, fingerprint: str | None = None):
    connection.execute(
        "INSERT INTO inv_requests (clave, operacion, fingerprint, respuesta_json, status_code) VALUES (?, ?, ?, ?, ?)",
        (clave, operacion, fingerprint, json.dumps(response, ensure_ascii=False), status_code),
    )


def _next_code(connection, prefix: str, table: str, column: str = "codigo") -> str:
    count = connection.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?", (f"{prefix}%",)
    ).fetchone()[0]
    return f"{prefix}{count + 1:03d}"


def _ensure_catalog(connection):
    connection.executemany("INSERT OR IGNORE INTO inv_zonas (id, nombre) VALUES (?, ?)", ZONES)
    connection.executemany(
        "INSERT OR IGNORE INTO inv_articulos (id, nombre, color) VALUES (?, ?, ?)", ARTICLES
    )
    for fixture in _FIXTURES:
        code, article, zone, state, net, cause = fixture
        connection.execute(
            """
            INSERT OR IGNORE INTO inv_mangas
                (codigo, articulo_id, zona_id, estado, neto, baja_causa, custodia_id, origen, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'Z-ALMACEN-PIEZAS', 'INVENTARIO', ?)
            """,
            (code, article, zone, state, net, cause, _now()),
        )
        if net is not None:
            connection.execute(
                """
                INSERT OR IGNORE INTO inv_pesajes (codigo, bruto, tara, neto, clave, created_at)
                VALUES (?, ?, '0.000', ?, ?, ?)
                """,
                (code, net, net, f"fixture-pesaje-{code}", _now()),
            )
    for code, cause in (
        ("INV-DEMO-FALTANTE", "FALTANTE"),
        ("INV-DEMO-NO-RECUPERABLE", "NO_RECUPERABLE"),
    ):
        manga = connection.execute(
            "SELECT neto, estado, baja_ref FROM inv_mangas WHERE codigo = ?", (code,)
        ).fetchone()
        if manga is not None and manga["neto"] is not None and manga["estado"] in {
            "BAJA_COMPROBADA", "BAJA_NO_RECUPERABLE",
        } and manga["baja_ref"] is None:
            reference = f"FIX-BAJA-{code}"
            connection.execute(
                "INSERT OR IGNORE INTO inv_fixture_bajas (codigo, causa, delta, referencia) VALUES (?, ?, ?, ?)",
                (code, cause, format(-Decimal(manga["neto"]), ".3f"), reference),
            )
            connection.execute(
                "UPDATE inv_mangas SET baja_ref = ? WHERE codigo = ? AND baja_ref IS NULL",
                (reference, code),
            )


def _return_article(connection, piece: str, color: str) -> str:
    normalized_piece = (piece or "PIEZA").strip().upper().replace(" ", "-")
    normalized_color = (color or "SIN-COLOR").strip().upper().replace(" ", "-")
    article_id = f"ART-{normalized_piece}-{normalized_color}"
    connection.execute(
        "INSERT OR IGNORE INTO inv_articulos (id, nombre, color) VALUES (?, ?, ?)",
        (article_id, (piece or "Pieza").strip().title(), (color or "Sin color").strip().title()),
    )
    return article_id


def _return_status(status: str) -> str:
    return {
        "available": "DISPONIBLE",
        "reserved": "RESERVADA",
        "pending": "PENDIENTE_PESAJE",
        "received": "RECIBIDA",
    }.get(status, "REFERENCIA_RETORNO")


def _sync_returns(connection):
    try:
        rows = connection.execute(
            """
            SELECT u.code, u.piece, u.color, u.status, r.net_kg
            FROM units u LEFT JOIN receipts r ON r.code = u.code
            WHERE r.net_kg IS NOT NULL
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return
    for row in rows:
        article_id = _return_article(connection, row["piece"], row["color"])
        state = _return_status(row["status"])
        existing = connection.execute(
            "SELECT codigo FROM inv_mangas WHERE codigo = ?", (row["code"],)
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO inv_mangas
                    (codigo, articulo_id, zona_id, estado, neto, custodia_id, origen, updated_at)
                VALUES (?, ?, NULL, ?, ?, 'Z-ALMACEN-PIEZAS', 'RETORNO', ?)
                """,
                (row["code"], article_id, state, row["net_kg"], _now()),
            )


def _initialize_path(db_path):
    path = str(db_path)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = _connect_path(path)
    try:
        connection.executescript(_SCHEMA)
        request_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(inv_requests)")
        }
        if "fingerprint" not in request_columns:
            connection.execute("ALTER TABLE inv_requests ADD COLUMN fingerprint TEXT")
        reading_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(inv_lecturas)")
        }
        if "zona_anterior" not in reading_columns:
            connection.execute("ALTER TABLE inv_lecturas ADD COLUMN zona_anterior TEXT")
        manga_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(inv_mangas)")
        }
        if "baja_ref" not in manga_columns:
            connection.execute("ALTER TABLE inv_mangas ADD COLUMN baja_ref TEXT")
        if "custodia_id" not in manga_columns:
            connection.execute("ALTER TABLE inv_mangas ADD COLUMN custodia_id TEXT")
        for column in ("estado_anterior", "bruto_anterior", "tara_anterior", "neto_anterior"):
            if column not in reading_columns:
                connection.execute(f"ALTER TABLE inv_lecturas ADD COLUMN {column} TEXT")
        _ensure_catalog(connection)
        _sync_returns(connection)
    finally:
        connection.close()


def _article(connection, article_id):
    row = connection.execute("SELECT * FROM inv_articulos WHERE id = ?", (article_id,)).fetchone()
    if row is None:
        raise InventoryError(f"No existe el artículo {article_id}", 404)
    return row


def _zone(connection, zone_id):
    row = connection.execute("SELECT * FROM inv_zonas WHERE id = ?", (zone_id,)).fetchone()
    if row is None:
        raise InventoryError(f"No existe la zona {zone_id}", 404)
    return row


def _manga(connection, code):
    row = connection.execute("SELECT * FROM inv_mangas WHERE codigo = ?", (code,)).fetchone()
    if row is None:
        _sync_returns(connection)
        row = connection.execute("SELECT * FROM inv_mangas WHERE codigo = ?", (code,)).fetchone()
    if row is None:
        reserved = connection.execute(
            "SELECT 1 FROM inv_preetiquetas WHERE codigo = ? AND estado = 'RESERVADA'", (code,)
        ).fetchone()
        if reserved:
            raise InventoryError(
                "La preetiqueta está reservada y aún no tiene una antigua vinculada",
                409,
                preetiqueta=True,
            )
        raise InventoryError(
            "QR no reconocido. Revisa la etiqueta antes de crear otra identidad.",
            404,
        )
    return row


def _state(connection):
    _sync_returns(connection)
    zones = [dict(row) for row in connection.execute("SELECT id, nombre FROM inv_zonas ORDER BY id")]
    articles = [dict(row) for row in connection.execute("SELECT id, nombre, color FROM inv_articulos ORDER BY id")]
    mangas = [
        dict(row)
        for row in connection.execute(
            "SELECT codigo, articulo_id AS articulo, zona_id AS zona, zona_id AS zona_hallazgo, "
            "custodia_id AS custodia, origen AS procedencia, estado, neto FROM inv_mangas ORDER BY codigo"
        )
    ]
    sessions = []
    for row in connection.execute("SELECT id, zona_id AS zona, estado FROM inv_sesiones ORDER BY id"):
        readings = [
            {"codigo": read["codigo"]}
            for read in connection.execute(
                "SELECT codigo FROM inv_lecturas WHERE sesion_id = ? ORDER BY codigo", (row["id"],)
            )
        ]
        sessions.append({**dict(row), "lecturas": readings})
    pending = [
        dict(row)
        for row in connection.execute(
            "SELECT codigo, articulo_id AS articulo, zona_id AS zona, estado, bruto, tara, neto "
            "FROM inv_pendientes ORDER BY codigo"
        )
    ]
    movements = [dict(row) for row in connection.execute("SELECT * FROM inv_movimientos ORDER BY id")]
    prelabels = [
        {"codigo": row["codigo"]}
        for row in connection.execute(
            "SELECT codigo FROM inv_preetiquetas WHERE estado = 'RESERVADA' ORDER BY codigo"
        )
    ]
    return {
        "zonas": zones,
        "articulos": articles,
        "mangas": mangas,
        "sesiones": sessions,
        "pendientes": pending,
        "movimientos": movements,
        "preetiquetas": prelabels,
    }


def inventory_state(db_path=None):
    """Consulta directa útil para el runner y para pruebas sin red."""
    app = current_app if db_path is None and has_app_context() else None
    path = _app_path(app=app, db_path=db_path)
    _initialize_path(path)
    connection = _connect_path(path)
    try:
        return _state(connection)
    finally:
        connection.close()


def label_data(codigo: str, db_path=None):
    """Devuelve identidad imprimible persistida, o ``None`` si no existe."""
    app = current_app if db_path is None and has_app_context() else None
    path = _app_path(app=app, db_path=db_path)
    if path != ":memory:" and not Path(path).exists():
        return None
    connection = _connect_path(path)
    try:
        row = connection.execute(
            """
            SELECT m.codigo, a.nombre AS pieza, a.color, z.nombre AS zona,
                   m.estado, m.bruto, m.tara, m.neto
            FROM inv_mangas m
            JOIN inv_articulos a ON a.id = m.articulo_id
            LEFT JOIN inv_zonas z ON z.id = m.zona_id
            WHERE m.codigo = ?
            """,
            (codigo,),
        ).fetchone()
        if row is not None:
            return dict(row)
        prelabel = connection.execute(
            "SELECT codigo, estado FROM inv_preetiquetas WHERE codigo = ?", (codigo,)
        ).fetchone()
        if prelabel is None:
            return None
        return {
            "codigo": prelabel["codigo"], "pieza": None, "color": None, "zona": None,
            "estado": prelabel["estado"], "bruto": None, "tara": None, "neto": None,
        }
    finally:
        connection.close()


def register_inventory_routes(app):
    """Inicializa el sublibro y registra sus rutas en la fábrica de mesa."""
    if app.extensions.get("mesa_central") is None:
        _initialize_path(app.config["MESA_DB_PATH"])
    from mesa_printer import register_printer_routes

    @app.teardown_appcontext
    def close_inventory_db(_error=None):
        connection = g.pop("inv_db", None)
        if connection is not None:
            connection.close()

    @app.errorhandler(InventoryError)
    def handle_inventory_error(error):
        return _json_error(error)

    @app.get(f"{BASE}/estado")
    def inventory_status():
        return jsonify(_state(_db()))

    @app.post(f"{BASE}/sesiones")
    def open_session():
        payload = _payload()
        zone_id = _text(payload, "zona")
        clave = _text(payload, "clave")
        connection = _db()
        _begin(connection)
        try:
            fp = _fingerprint({"zona": zone_id})
            replay = _request_replay(connection, clave, "sesion", fp)
            if replay:
                connection.commit()
                return jsonify(replay[0]), replay[1]
            _zone(connection, zone_id)
            session_id = _next_code(connection, "INV-SES-", "inv_sesiones", "id")
            connection.execute(
                "INSERT INTO inv_sesiones (id, zona_id, estado, clave, created_at) VALUES (?, ?, 'ABIERTA', ?, ?)",
                (session_id, zone_id, clave, _now()),
            )
            response = {"id": session_id}
            _save_request(connection, clave, "sesion", response, 201, fp)
            connection.commit()
            return jsonify(response), 201
        except Exception:
            connection.rollback()
            raise

    @app.post(f"{BASE}/sesiones/<session_id>/lecturas")
    def read_session(session_id):
        payload = _payload()
        code = _text(payload, "codigo")
        connection = _db()
        _begin(connection)
        try:
            session = connection.execute("SELECT * FROM inv_sesiones WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise InventoryError("No existe la sesión", 404)
            if session["estado"] != "ABIERTA":
                raise InventoryError("La sesión ya está cerrada", 409)
            manga = _manga(connection, code)
            if manga["estado"] == "BAJA_NO_RECUPERABLE":
                raise InventoryError("La manga está bloqueada por causa no recuperable", 409)
            existing = connection.execute(
                "SELECT 1 FROM inv_lecturas WHERE sesion_id = ? AND codigo = ?", (session_id, code)
            ).fetchone()
            if existing:
                connection.commit()
                return jsonify(mensaje="Lectura ya registrada"), 200
            previous_zone = manga["zona_id"]
            if manga["zona_id"] is None:
                connection.execute(
                    "UPDATE inv_mangas SET zona_id = ?, updated_at = ? WHERE codigo = ?",
                    (session["zona_id"], _now(), code),
                )
            elif manga["zona_id"] != session["zona_id"]:
                confirmed = payload.get("confirmar_zona") is True
                previous_zone = payload.get("zona_anterior")
                if not confirmed or previous_zone != manga["zona_id"]:
                    anterior = _zone(connection, manga["zona_id"])["nombre"]
                    actual = _zone(connection, session["zona_id"])["nombre"]
                    raise InventoryError(
                        f"{code} figura en {anterior}. ¿La encontraste en {actual}?",
                        409,
                        zona_anterior=manga["zona_id"],
                    )
                connection.execute(
                    "UPDATE inv_mangas SET zona_id = ?, updated_at = ? WHERE codigo = ?",
                    (session["zona_id"], _now(), code),
                )
            message = "Lectura registrada"
            repeated_elsewhere = connection.execute(
                "SELECT sesion_id FROM inv_lecturas WHERE codigo = ? AND sesion_id <> ? LIMIT 1",
                (code, session_id),
            ).fetchone()
            if repeated_elsewhere:
                message = "Lectura repetida en otra sesión; se conserva esta observación"
            if manga["estado"] == "BAJA_COMPROBADA" and manga["baja_causa"] == "FALTANTE":
                connection.execute(
                    "UPDATE inv_mangas SET estado = 'PENDIENTE_REPESAJE', bruto = NULL, tara = NULL, neto = NULL, updated_at = ? WHERE codigo = ?",
                    (_now(), code),
                )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO inv_pendientes
                        (codigo, articulo_id, zona_id, estado, bruto, tara, neto, created_at)
                    VALUES (?, ?, ?, 'PENDIENTE_REPESAJE', ?, ?, ?, ?)
                    """,
                    (code, manga["articulo_id"], session["zona_id"], None, None, None, _now()),
                )
                message = "Lectura registrada; pendiente de repesaje"
            elif manga["estado"] == "PENDIENTE_PESAJE":
                connection.execute(
                    """
                    INSERT OR REPLACE INTO inv_pendientes
                        (codigo, articulo_id, zona_id, estado, bruto, tara, neto, created_at)
                    VALUES (?, ?, ?, 'PENDIENTE_PESAJE', NULL, NULL, NULL, ?)
                    """,
                    (code, manga["articulo_id"], session["zona_id"], _now()),
                )
            connection.execute(
                """
                INSERT INTO inv_lecturas
                    (sesion_id, codigo, zona_anterior, estado_anterior, bruto_anterior, tara_anterior, neto_anterior, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, code, previous_zone, manga["estado"], manga["bruto"], manga["tara"], manga["neto"], _now()),
            )
            connection.commit()
            return jsonify(mensaje=message), 201
        except Exception:
            connection.rollback()
            raise

    @app.delete(f"{BASE}/sesiones/<session_id>/lecturas/<code>")
    def delete_session_reading(session_id, code):
        connection = _db()
        _begin(connection)
        try:
            session = connection.execute("SELECT estado, closed_at FROM inv_sesiones WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise InventoryError("No existe la sesión", 404)
            if session["estado"] != "ABIERTA":
                raise InventoryError("La sesión ya está cerrada", 409)
            reading = connection.execute(
                "SELECT rowid AS reading_rowid, * FROM inv_lecturas WHERE sesion_id = ? AND codigo = ?",
                (session_id, code),
            ).fetchone()
            if reading is None:
                raise InventoryError("La lectura no existe en la sesión", 404)
            manga = _manga(connection, code)
            credited = connection.execute(
                "SELECT 1 FROM inv_movimientos WHERE codigo = ? AND CAST(delta AS REAL) > 0 LIMIT 1",
                (code,),
            ).fetchone()
            if manga["estado"] in {"PESADA_PENDIENTE_CONFIRMACION", "RECIBIDA"} or credited:
                raise InventoryError("No se puede retirar una lectura después de pesar o acreditar", 409)
            connection.execute(
                "DELETE FROM inv_lecturas WHERE sesion_id = ? AND codigo = ?", (session_id, code)
            )
            latest = connection.execute(
                "SELECT rowid AS reading_rowid, * FROM inv_lecturas WHERE codigo = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (code,),
            ).fetchone()
            deleted_is_latest = latest is None or (
                latest["created_at"], latest["reading_rowid"]
            ) <= (reading["created_at"], reading["reading_rowid"])
            if deleted_is_latest:
                connection.execute(
                    "UPDATE inv_mangas SET zona_id = ?, estado = ?, bruto = ?, tara = ?, neto = ?, updated_at = ? WHERE codigo = ?",
                    (reading["zona_anterior"], reading["estado_anterior"], reading["bruto_anterior"], reading["tara_anterior"], reading["neto_anterior"], _now(), code),
                )
                # A Mesa-created identity already has a PENDIENTE_PESAJE row.
                # Removing an accidental C66 observation must restore only the
                # manga snapshot, not erase the work that is still waiting for
                # its first weighing.  A BAJA_COMPROBADA observation, however,
                # creates a repesaje pending as part of the reading and can be
                # rolled back with that reading.
                if reading["estado_anterior"] == "BAJA_COMPROBADA":
                    connection.execute("DELETE FROM inv_pendientes WHERE codigo = ?", (code,))
                elif reading["estado_anterior"] == "PENDIENTE_PESAJE":
                    # The accidental observation may have changed the finding
                    # zone. Keep the Mesa pending, but put it back at the zone
                    # that belonged to the identity before that observation.
                    restored = connection.execute(
                        """
                        UPDATE inv_pendientes
                           SET articulo_id = ?, zona_id = ?, estado = 'PENDIENTE_PESAJE',
                               bruto = NULL, tara = NULL, neto = NULL
                         WHERE codigo = ?
                        """,
                        (manga["articulo_id"], reading["zona_anterior"], code),
                    )
                    if restored.rowcount == 0:
                        connection.execute(
                            """
                            INSERT INTO inv_pendientes
                                (codigo, articulo_id, zona_id, estado, bruto, tara, neto, created_at)
                            VALUES (?, ?, ?, 'PENDIENTE_PESAJE', NULL, NULL, NULL, ?)
                            """,
                            (code, manga["articulo_id"], reading["zona_anterior"], _now()),
                        )
            connection.commit()
            return jsonify(mensaje="Lectura eliminada"), 200
        except Exception:
            connection.rollback()
            raise

    @app.post(f"{BASE}/sesiones/<session_id>/cerrar")
    def close_session(session_id):
        connection = _db()
        _begin(connection)
        try:
            session = connection.execute("SELECT estado, closed_at FROM inv_sesiones WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                raise InventoryError("No existe la sesión", 404)
            closed_at = session["closed_at"]
            if session["estado"] == "ABIERTA":
                closed_at = _now()
                connection.execute(
                    "UPDATE inv_sesiones SET estado = 'CERRADA', closed_at = ? WHERE id = ?",
                    (_now(), session_id),
                )
            connection.commit()
            quantity = connection.execute(
                "SELECT COUNT(*) FROM inv_lecturas WHERE sesion_id = ?", (session_id,)
            ).fetchone()[0]
            return jsonify(mensaje="Sesión cerrada", closed_at=closed_at, cantidad=quantity), 200
        except Exception:
            connection.rollback()
            raise

    @app.post(f"{BASE}/preetiquetas")
    def reserve_prelabel():
        payload = _payload()
        clave = _text(payload, "clave")
        connection = _db()
        _begin(connection)
        try:
            replay = _request_replay(connection, clave, "preetiqueta", _fingerprint({}))
            if replay:
                connection.commit()
                return jsonify(replay[0]), replay[1]
            code = _next_code(connection, "INV-", "inv_preetiquetas")
            connection.execute(
                "INSERT INTO inv_preetiquetas (codigo, clave, estado, created_at) VALUES (?, ?, 'RESERVADA', ?)",
                (code, clave, _now()),
            )
            response = {"codigo": code}
            _save_request(connection, clave, "preetiqueta", response, 201, _fingerprint({}))
            connection.commit()
            return jsonify(response), 201
        except Exception:
            connection.rollback()
            raise

    @app.post(f"{BASE}/antiguas")
    def register_old_unit():
        payload = _payload()
        raw_code = payload.get("codigo", "")
        if not isinstance(raw_code, str):
            raise InventoryError("codigo debe ser texto", 422)
        supplied_code = raw_code.strip()
        article_id = _text(payload, "articulo")
        zone_id = _text(payload, "zona")
        session_id = _text(payload, "sesion", required=False)
        clave = _text(payload, "clave")
        connection = _db()
        _begin(connection)
        try:
            fp = _fingerprint({"codigo": supplied_code, "articulo": article_id, "zona": zone_id, "sesion": session_id})
            replay = _request_replay(connection, clave, "antigua", fp)
            if replay:
                connection.commit()
                return jsonify(replay[0]), replay[1]
            _article(connection, article_id)
            _zone(connection, zone_id)
            if session_id:
                session = connection.execute("SELECT estado, zona_id FROM inv_sesiones WHERE id = ?", (session_id,)).fetchone()
                if session is None:
                    raise InventoryError("No existe la sesión", 404)
                if session["estado"] != "ABIERTA":
                    raise InventoryError("La sesión ya está cerrada", 409)
                if session["zona_id"] != zone_id:
                    raise InventoryError("La sesión pertenece a otra zona", 409, zona_anterior=zone_id)
            code = supplied_code
            status_code = 201
            if not code:
                code = _next_code(connection, "INV-MESA-", "inv_mangas")
            prelabel = connection.execute(
                "SELECT estado FROM inv_preetiquetas WHERE codigo = ?", (code,)
            ).fetchone()
            existing = connection.execute("SELECT * FROM inv_mangas WHERE codigo = ?", (code,)).fetchone()
            if existing is not None:
                if existing["articulo_id"] != article_id or existing["zona_id"] != zone_id:
                    raise InventoryError("El código ya está vinculado a otra identidad", 409)
                if existing["estado"] != "PENDIENTE_PESAJE":
                    raise InventoryError("La identidad ya existe en otra condición", 409)
                status_code = 200
            elif supplied_code and prelabel is None:
                raise InventoryError("El código no corresponde a una preetiqueta reservada", 404)
            else:
                connection.execute(
                    """
                    INSERT INTO inv_mangas
                        (codigo, articulo_id, zona_id, estado, custodia_id, origen, updated_at)
                    VALUES (?, ?, ?, 'PENDIENTE_PESAJE', 'Z-ALMACEN-PIEZAS', 'INVENTARIO', ?)
                    """,
                    (code, article_id, zone_id, _now()),
                )
                if prelabel:
                    connection.execute("UPDATE inv_preetiquetas SET estado = 'VINCULADA' WHERE codigo = ?", (code,))
            connection.execute(
                """INSERT OR IGNORE INTO inv_pendientes
                   (codigo, articulo_id, zona_id, estado, created_at)
                   VALUES (?, ?, ?, 'PENDIENTE_PESAJE', ?)""",
                (code, article_id, zone_id, _now()),
            )
            if session_id:
                connection.execute(
                    "INSERT OR IGNORE INTO inv_lecturas (sesion_id, codigo, zona_anterior, created_at) VALUES (?, ?, ?, ?)",
                    (session_id, code, zone_id, _now()),
                )
            response = {"codigo": code}
            _save_request(connection, clave, "antigua", response, status_code, fp)
            connection.commit()
            return jsonify(response), status_code
        except Exception:
            connection.rollback()
            raise

    @app.post(f"{BASE}/pesajes")
    def weigh_unit():
        payload = _payload()
        code = _text(payload, "codigo")
        clave = _text(payload, "clave")
        bruto = _parse_grams(payload.get("bruto"), "bruto", positive=True)
        tara = _parse_grams(payload.get("tara"), "tara", positive=False)
        neto = _subtract_grams(bruto, tara)
        scale_reader = current_app.extensions.get("mesa_scale_reader")
        scale_token = payload.get("scale_token")
        connection = _db()
        _begin(connection)
        try:
            fp = _fingerprint({"codigo": code, "bruto": bruto, "tara": tara})
            replay = _request_replay(connection, clave, "pesaje", fp)
            if replay:
                connection.commit()
                return jsonify(replay[0]), replay[1]
            if scale_reader is not None:
                if not isinstance(scale_token, str) or not scale_token.strip():
                    raise InventoryError("El pesaje físico requiere una captura de balanza", 409)
                try:
                    capture = validate_capture(connection, scale_token.strip(), code, expected_kg=bruto)
                except ScaleCaptureError as error:
                    raise InventoryError(str(error), 409)
                if capture["base"] == "NT" and payload.get("confirmar_sin_tara_indicador") is not True and not (
                    Decimal(tara) == Decimal("0.000") and payload.get("confirmar_tara_cero") is True
                ):
                    raise InventoryError(
                        "La lectura NT requiere confirmar que el indicador no fue tarado", 409
                    )
            manga = _manga(connection, code)
            reappearance = manga["estado"] == "BAJA_COMPROBADA" and manga["baja_causa"] == "FALTANTE"
            if reappearance and not connection.execute(
                "SELECT 1 FROM inv_lecturas WHERE codigo = ? LIMIT 1", (code,)
            ).fetchone():
                raise InventoryError("La baja requiere un hallazgo en una sesión antes del repesaje", 409)
            if manga["estado"] not in {"PENDIENTE_PESAJE", "PENDIENTE_REPESAJE"} and not reappearance:
                raise InventoryError("La manga no está pendiente de pesaje", 409)
            connection.execute(
                "UPDATE inv_mangas SET bruto = ?, tara = ?, neto = ?, estado = 'PESADA_PENDIENTE_CONFIRMACION', updated_at = ? WHERE codigo = ?",
                (bruto, tara, neto, _now(), code),
            )
            connection.execute(
                "INSERT INTO inv_pesajes (codigo, bruto, tara, neto, clave, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (code, bruto, tara, neto, clave, _now()),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO inv_pendientes
                    (codigo, articulo_id, zona_id, estado, bruto, tara, neto, created_at)
                VALUES (?, ?, ?, 'PESADA_PENDIENTE_CONFIRMACION', ?, ?, ?, ?)
                """,
                (code, manga["articulo_id"], manga["zona_id"], bruto, tara, neto, _now()),
            )
            response = {"codigo": code, "neto": neto}
            _save_request(connection, clave, "pesaje", response, 201, fp)
            if scale_reader is not None:
                consume_capture(connection, scale_token.strip())
            connection.commit()
            return jsonify(response), 201
        except Exception:
            connection.rollback()
            raise

    @app.post(f"{BASE}/revision")
    def start_review():
        payload = _payload()
        code = _text(payload, "codigo")
        if not all(payload.get(flag) is True for flag in ("cobertura", "movimientos_revisados", "busqueda")):
            raise InventoryError("La revisión requiere cubrir las cuatro zonas y resolver movimientos/datos", 409)
        connection = _db()
        _begin(connection)
        try:
            manga = _manga(connection, code)
            if manga["estado"] not in {"DISPONIBLE", "RECIBIDA"}:
                raise InventoryError("La manga no está activa para revisión", 409)
            active = connection.execute(
                "SELECT token, neto FROM inv_revisiones WHERE codigo = ? AND estado = 'ACTIVA'", (code,)
            ).fetchone()
            if active:
                connection.commit()
                return jsonify(token=active["token"], neto=active["neto"]), 200
            observed = connection.execute(
                "SELECT 1 FROM inv_lecturas WHERE codigo = ? LIMIT 1", (code,)
            ).fetchone()
            if observed:
                raise InventoryError("La manga ya fue observada en este inventario", 409)
            token = f"REV-{uuid.uuid4().hex}"
            connection.execute(
                "INSERT INTO inv_revisiones (token, codigo, estado, neto, created_at) VALUES (?, ?, 'ACTIVA', ?, ?)",
                (token, code, manga["neto"], _now()),
            )
            connection.commit()
            return jsonify(token=token, neto=manga["neto"]), 201
        except Exception:
            connection.rollback()
            raise

    @app.post(f"{BASE}/faltantes")
    def register_missing():
        payload = _payload()
        code = _text(payload, "codigo")
        token = _text(payload, "token")
        reason = _text(payload, "motivo")
        clave = _text(payload, "clave")
        connection = _db()
        _begin(connection)
        try:
            fp = _fingerprint({"codigo": code, "token": token, "motivo": reason})
            replay = _request_replay(connection, clave, "faltante", fp)
            if replay:
                connection.commit()
                return jsonify(replay[0]), replay[1]
            review = connection.execute(
                "SELECT * FROM inv_revisiones WHERE token = ? AND codigo = ? AND estado = 'ACTIVA'",
                (token, code),
            ).fetchone()
            if review is None:
                raise InventoryError("La revisión no está activa o ya fue utilizada", 409)
            newer_reading = connection.execute(
                "SELECT 1 FROM inv_lecturas WHERE codigo = ? AND created_at > ? LIMIT 1",
                (code, review["created_at"]),
            ).fetchone()
            if newer_reading:
                raise InventoryError("El token de revisión quedó obsoleto por una nueva lectura", 409)
            manga = _manga(connection, code)
            if manga["estado"] != "DISPONIBLE":
                raise InventoryError("La manga ya no está activa para ajuste", 409)
            if not manga["neto"]:
                raise InventoryError("La manga no tiene neto vigente para ajustar", 409)
            connection.execute(
                "INSERT INTO inv_movimientos (codigo, tipo, delta, motivo, clave, created_at) VALUES (?, 'AJUSTE_FALTANTE', ?, ?, ?, ?)",
                (code, format(-Decimal(manga["neto"]), ".3f"), reason, clave, _now()),
            )
            movement_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "UPDATE inv_mangas SET estado = 'BAJA_COMPROBADA', baja_causa = 'FALTANTE', baja_movimiento_id = ?, updated_at = ? WHERE codigo = ?",
                (movement_id, _now(), code),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO inv_pendientes
                    (codigo, articulo_id, zona_id, estado, bruto, tara, neto, created_at)
                VALUES (?, ?, ?, 'PENDIENTE_REPESAJE', NULL, NULL, NULL, ?)
                """,
                (code, manga["articulo_id"], manga["zona_id"], _now()),
            )
            connection.execute(
                "UPDATE inv_revisiones SET estado = 'CONSUMIDA', used_at = ? WHERE token = ?", (_now(), token)
            )
            response = {"codigo": code, "comprobante": f"AJ-{movement_id:04d}", "movimiento_id": movement_id}
            _save_request(connection, clave, "faltante", response, 201, fp)
            connection.commit()
            return jsonify(response), 201
        except Exception:
            connection.rollback()
            raise

    @app.post(f"{BASE}/confirmaciones")
    def confirm_unit():
        payload = _payload()
        code = _text(payload, "codigo")
        reason = _text(payload, "motivo")
        clave = _text(payload, "clave")
        connection = _db()
        _begin(connection)
        try:
            fp = _fingerprint({"codigo": code, "motivo": reason})
            replay = _request_replay(connection, clave, "confirmacion", fp)
            if replay:
                connection.commit()
                return jsonify(replay[0]), replay[1]
            manga = _manga(connection, code)
            if manga["estado"] == "BAJA_NO_RECUPERABLE":
                raise InventoryError("La manga está bloqueada por causa no recuperable", 409)
            if manga["estado"] in {"DISPONIBLE", "RECIBIDA"}:
                raise InventoryError("La manga ya está activa; no se duplica el alta", 409)
            if manga["estado"] != "PESADA_PENDIENTE_CONFIRMACION":
                raise InventoryError("La manga requiere un pesaje vigente antes de confirmar", 409)
            if not manga["neto"]:
                raise InventoryError("La manga no tiene neto vigente para confirmar", 409)
            link = manga["baja_movimiento_id"] or manga["baja_ref"]
            movement_type = "REINGRESO" if link else "ALTA_INVENTARIO"
            connection.execute(
                "INSERT INTO inv_movimientos (codigo, tipo, delta, motivo, clave, vinculo_baja, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (code, movement_type, format(Decimal(manga["neto"]), ".3f"), reason, clave, link, _now()),
            )
            movement_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "UPDATE inv_mangas SET estado = 'DISPONIBLE', baja_causa = NULL, baja_movimiento_id = NULL, baja_ref = NULL, updated_at = ? WHERE codigo = ?",
                (_now(), code),
            )
            connection.execute("DELETE FROM inv_pendientes WHERE codigo = ?", (code,))
            response = {"codigo": code, "movimiento_id": movement_id, "vinculo_baja": link}
            _save_request(connection, clave, "confirmacion", response, 201, fp)
            connection.commit()
            return jsonify(response), 201
        except Exception:
            connection.rollback()
            raise

    register_printer_routes(app)
    return app


def _parse_grams(value, field: str, *, positive: bool) -> str:
    if not isinstance(value, str) or not _GRAMS.fullmatch(value.strip()):
        raise InventoryError(f"{field} debe expresarse en gramos exactos con tres decimales", 422)
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise InventoryError(f"{field} no es válido", 422)
    if (positive and number <= 0) or (not positive and number < 0):
        raise InventoryError(f"{field} debe ser válido y no negativo", 422)
    return format(number, ".3f")


def _subtract_grams(bruto: str, tara: str) -> str:
    net = Decimal(bruto) - Decimal(tara)
    if net <= 0:
        raise InventoryError("El neto derivado debe ser mayor que cero", 422)
    return format(net, ".3f")


__all__ = ["inventory_state", "label_data", "register_inventory_routes"]
