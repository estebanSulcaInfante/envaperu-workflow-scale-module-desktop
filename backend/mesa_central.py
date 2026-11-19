"""Conexión de la mesa con la cuenta de dispositivo asignada en Central."""
import hashlib
import json
import os
import socket
import sqlite3
import uuid
from contextlib import closing
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from flask import jsonify, request

from mesa_logging import get_correlation_id
from mesa_scale import ScaleCaptureError, validate_capture


class CentralError(Exception):
    def __init__(self, message, status, details=None):
        super().__init__(message)
        self.status = status
        self.details = details or {}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class CentralStation:
    def __init__(self, url, token):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("La conexión con Central requiere una dirección HTTPS directa.")
        if not token:
            raise ValueError("Falta la credencial de Estación 2.")
        self.url = url.rstrip("/")
        self._token = token
        self._opener = build_opener(NoRedirect)

    @classmethod
    def from_environment(cls, url):
        return cls(url, os.environ.pop("MESA_CENTRAL_TOKEN", ""))

    def call(self, method, path, body=None, key=None):
        headers = {"Authorization": "Bearer " + self._token, "Content-Type": "application/json",
                   "X-Correlation-ID": get_correlation_id() or str(uuid.uuid4())}
        if key:
            headers["Idempotency-Key"] = str(key)
        req = Request(self.url + path, method=method, headers=headers,
                      data=json.dumps(body, allow_nan=False).encode() if body is not None else None)
        try:
            with self._opener.open(req, timeout=12) as res:
                return json.load(res), res.status
        except HTTPError as exc:
            details = {}
            with exc:
                try:
                    error = json.load(exc).get("error")
                    if isinstance(error, dict) and isinstance(error.get("details"), dict):
                        details = {k: error["details"][k] for k in ("zona_anterior", "zona_actual")
                                   if k in error["details"]}
                    error = error.get("message") if isinstance(error, dict) else error
                except (ValueError, AttributeError):
                    error = None
            status = exc.code if 400 <= exc.code < 600 else 502
            raise CentralError(error if isinstance(error, str) else "Central rechazó la operación.", status, details) from exc
        except (URLError, OSError, socket.timeout, ValueError) as exc:
            raise CentralError("Sin respuesta de Central. Reintenta la misma operación para consultar su resultado.", 503) from exc

    def label(self, code, area):
        return self.call("GET", "/" + area + "/etiqueta/" + quote(code, safe=""))[0]


def _measurement_envelope(db, path, data, key):
    """Congela el envío antes de la red. Un reintento conserva lectura y clave."""
    token = data.pop("scale_token", None)
    if not token or not isinstance(token, str):
        raise CentralError("Captura el peso estable de la balanza.", 409)
    code = data.get("codigo") if path.endswith("pesajes") else data.get("code")
    digest = hashlib.sha256(json.dumps([path, data, token], sort_keys=True).encode()).hexdigest()
    with closing(sqlite3.connect(db, timeout=8)) as conn, conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT * FROM mesa_envio_pesaje WHERE clave=?", (str(key),)).fetchone()
        if previous:
            if previous["huella"] != digest:
                raise CentralError("La operación pendiente corresponde a otra medición.", 409)
            return json.loads(previous["contenido"])
        expected = data.get("bruto") if path.endswith("pesajes") else data.get("net_kg")
        try:
            if not Decimal(str(expected)).is_finite():
                raise ValueError()
            capture = validate_capture(conn, token, code, expected_kg=expected)
        except (ScaleCaptureError, InvalidOperation, ValueError) as exc:
            raise CentralError("La captura no corresponde al peso o ha caducado. Vuelve a pesar.", 409) from exc
        if path == "/receive" and capture["base"] != "NT":
            raise CentralError("El retorno requiere el neto de la balanza.", 409)
        if path.endswith("pesajes") and capture["base"] == "NT" and data.get("confirmar_sin_tara_indicador") is not True and not (
                Decimal(str(data.get("tara", -1))) == 0 and data.get("confirmar_tara_cero") is True):
            raise CentralError("Confirma que la balanza está sin tarar.", 409)
        data["captura"] = {k: capture[k] for k in ("token", "codigo", "kg", "base", "captured_at")}
        try:
            conn.execute("INSERT INTO mesa_envio_pesaje VALUES (?,?,?,?)",
                         (str(key), token, digest, json.dumps(data)))
        except sqlite3.IntegrityError as exc:
            raise CentralError("La lectura ya pertenece a otra operación.", 409) from exc
        return data


def bind_central(app, central):
    db = app.config["MESA_DB_PATH"]
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS mesa_envio_pesaje "
                     "(clave TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE, huella TEXT NOT NULL, contenido TEXT NOT NULL)")

    @app.errorhandler(CentralError)
    def central_error(exc):
        return jsonify(error=str(exc), **exc.details), exc.status

    @app.before_request
    def central_operations():
        if not request.path.startswith("/api/mesa/"):
            return
        path = request.path.removeprefix("/api/mesa")
        if path.startswith(("/balanza", "/qr/", "/printer/", "/retornos/etiquetas/", "/inventario/etiquetas/")):
            return
        if path not in {"/state", "/receive", "/unions"} and not path.startswith("/inventario/"):
            raise CentralError("Operación de estación desconocida.", 404)
        if request.method == "GET":
            result, status = central.call("GET", quote(path, safe="/"))
        else:
            data = request.get_json(silent=True) or {}
            if not isinstance(data, dict) or "captura" in data:
                raise CentralError("Solicitud de estación inválida.", 422)
            supplied = data.get("clave") or data.get("request_id")
            if path == "/unions":
                supplied = json.dumps(sorted(data.get("codes", [])))
            key = uuid.uuid5(uuid.NAMESPACE_URL, path + "|" + str(supplied)) if supplied else uuid.uuid4()
            if path in {"/receive", "/inventario/pesajes"}:
                if not supplied:
                    raise CentralError("Falta la clave de confirmación.", 422)
                data = _measurement_envelope(db, path, data, key)
            result, status = central.call(request.method, quote(path, safe="/"), data, key)
        return jsonify(result), status
