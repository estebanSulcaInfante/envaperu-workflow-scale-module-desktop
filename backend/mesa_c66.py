"""Acceso del lector al piloto mediante un enlace emitido en la mesa."""
import io
import re
import secrets
import threading
import time

import qrcode
from flask import Response, render_template_string
from qrcode.image.svg import SvgPathImage
from werkzeug.wrappers import Request, Response as HttpResponse


BASE = "/api/mesa/inventario"
READING = re.compile(re.escape(BASE) + r"/sesiones/[\w-]+/(lecturas|cerrar)")
REMOVAL = re.compile(re.escape(BASE) + r"/sesiones/[\w-]+/lecturas/[\w.-]+")


class ReaderAccess:
    def __init__(self, app, authority):
        self.app = app
        self.authority = authority
        self.session = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.ticket = ""
        self.expires = 0

    def pairing_page(self):
        with self.lock:
            self.ticket = secrets.token_urlsafe(28)
            self.expires = time.monotonic() + 600
            url = f"http://{self.authority}/vincular/{self.ticket}"
        data = io.BytesIO()
        qrcode.make(url, image_factory=SvgPathImage).save(data)
        html = render_template_string("""<!doctype html><html lang="es"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>Conectar C66</title>
        <main style="max-width:32rem;margin:3rem auto;padding:1rem;font:18px system-ui">
        <a href="/inventario/mesa">Volver a la mesa</a><h1>Conectar C66</h1>
        <p>Desde la misma red de la mesa, escanea este QR con el C66 y abre el enlace.
        Puedes usarlo una vez durante los próximos 10 minutos.</p>{{ image|safe }}
        <p><a href="{{ url }}">Abrir escaneo en este equipo</a></p>
        <p><a href="/api/mesa/inventario/etiquetas/INV-DEMO-001/identidad.svg" target="_blank" rel="noreferrer">
        Ver QR de una manga de prueba</a></p></main></html>""",
                                      image=data.getvalue().decode().split("?>")[-1], url=url)
        return Response(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    @Request.application
    def __call__(self, req):
        if req.host != self.authority:
            return HttpResponse("Dirección incorrecta", status=403)
        if req.method == "GET" and req.path.startswith("/vincular/"):
            with self.lock:
                ticket = req.path.removeprefix("/vincular/")
                if not self.ticket or not secrets.compare_digest(ticket.encode(), self.ticket.encode()) or time.monotonic() >= self.expires:
                    return HttpResponse("Abre Conectar C66 en la mesa para obtener otro QR.", status=403)
                self.ticket = ""
            response = HttpResponse(status=303, headers={"Location": "/inventario/c66", "Cache-Control": "no-store",
                                                        "Referrer-Policy": "no-referrer"})
            response.set_cookie("lector_mesa", self.session, httponly=True, samesite="Strict")
            return response
        if not secrets.compare_digest(req.cookies.get("lector_mesa", "").encode(), self.session.encode()):
            return HttpResponse("Vincula el C66 desde la mesa.", status=403)
        if req.method in {"GET", "HEAD"}:
            allowed = req.path in {"/inventario/c66", BASE + "/estado"} or req.path.startswith("/assets/")
        elif req.method in {"POST", "DELETE"} and req.headers.get("Origin") == "http://" + self.authority:
            allowed = ((req.method == "POST" and (req.path in {BASE + "/sesiones"} or READING.fullmatch(req.path)))
                       or (req.method == "DELETE" and REMOVAL.fullmatch(req.path)))
        else:
            allowed = False
        if not allowed:
            return HttpResponse("Operación disponible solo en la mesa.", status=403)
        env = req.environ.copy()
        # La puerta ya comprobó dispositivo, ruta y origen antes del salto al servicio de mesa.
        env.update(HTTP_HOST="127.0.0.1", HTTP_ORIGIN="http://127.0.0.1")
        return HttpResponse.from_app(self.app, env)
