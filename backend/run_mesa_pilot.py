"""Mesa local de retornos e inventario, con acceso opcional para el lector C66."""
import argparse
import ipaddress
import sys
import threading
import webbrowser
from pathlib import Path

from flask import Response, abort, request, send_from_directory

from mesa_pilot import create_app
from mesa_c66 import ReaderAccess
from mesa_inventory import label_data
from mesa_inventory_sticker import render_sticker
from mesa_logging import log_shutdown, log_startup
from mesa_scale import MesaScaleReader


BACKEND = Path(__file__).resolve().parent
UI = Path(getattr(sys, "_MEIPASS", BACKEND.parent)) / "build" / "mesa-frontend"


def station_app(database, reader_address=None, scale_port=None, *, scale_unconfigured=False, central=None):
    scale_reader = MesaScaleReader(scale_port, configured=bool(scale_port)) if scale_port or scale_unconfigured else None
    if central is not None and scale_reader is None:
        raise ValueError("La estación conectada a Central requiere la balanza.")
    app = create_app(database, scale_reader=scale_reader, central=central)
    reader = ReaderAccess(app, reader_address) if reader_address else None
    listener_started = None
    if scale_reader is not None:
        listener_started = scale_reader.start()
    log_startup(
        database_path=database,
        scale_configured=bool(scale_port),
        reader_started=listener_started,
    )

    @app.before_request
    def check_local_host():
        if request.host.split(":")[0] not in {"localhost", "127.0.0.1"}:
            abort(403)

    if central is not None:
        from mesa_central import bind_central
        bind_central(app, central)

    @app.get("/")
    @app.get("/inventario/c66")
    @app.get("/inventario/mesa")
    @app.get("/inventario/revision")
    def station():
        return send_from_directory(UI, "mesa.html", max_age=0)

    @app.get("/inventario/conectar")
    def connect():
        if reader is None:
            return Response("Inicie la mesa con la dirección de red del C66 para vincular el lector.", status=503)
        return reader.pairing_page()

    @app.get("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(UI / "assets", filename)

    @app.get("/api/mesa/inventario/etiquetas/<codigo>/<kind>.<output>")
    def label(codigo, kind, output):
        unit = central.label(codigo, "inventario") if central else label_data(codigo, db_path=app.config["MESA_DB_PATH"])
        if unit is None:
            return {"error": "Identidad no encontrada"}, 404
        media = request.args.get("formato", "50x50")
        try:
            content = render_sticker(unit, kind, media, output)
        except ValueError as error:
            return {"error": str(error)}, 422
        if output == "svg":
            return Response(content, mimetype="image/svg+xml", headers={"Cache-Control": "no-store"})
        return Response(content.encode("utf-8"), mimetype="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{codigo}-{kind}-{media}.tspl"',
                                 "Cache-Control": "no-store"})

    return app, reader


def main():
    from waitress import create_server

    parser = argparse.ArgumentParser(description="Mesa de Armado e inventario local")
    parser.add_argument("--port", default=5196, type=int)
    parser.add_argument("--c66-host", type=ipaddress.IPv4Address)
    parser.add_argument("--c66-port", default=5198, type=int)
    scale = parser.add_mutually_exclusive_group()
    scale.add_argument("--scale-port", help="Puerto COM de la Accura")
    scale.add_argument("--scale-unconfigured", action="store_true", help="Modo físico en espera de configurar el COM")
    parser.add_argument("--central", help="URL HTTPS del servicio de Estación 2 en Central")
    parser.add_argument("--open-browser", action="store_true", help="Abrir la vista local al iniciar")
    parser.add_argument("--db", type=Path, default=BACKEND / "instance" / "mesa-pilot.sqlite3")
    args = parser.parse_args()
    if not (UI / "mesa.html").is_file():
        parser.exit(1, "Primero construya la interfaz con vite.mesa.config.js.\n")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    if args.c66_host and not any(args.c66_host in ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
        parser.error("Indique la dirección privada de la PC en la red del lector")
    authority = f"{args.c66_host}:{args.c66_port}" if args.c66_host else None
    central = None
    if args.central:
        from mesa_central import CentralStation
        central = CentralStation.from_environment(args.central)
    app, reader = station_app(args.db, authority, args.scale_port, scale_unconfigured=args.scale_unconfigured, central=central)
    station = create_server(app, host="127.0.0.1", port=args.port, map={})
    mobile = None
    scale_reader = app.extensions.get("mesa_scale_reader")
    try:
        if reader:
            mobile = create_server(reader, host=str(args.c66_host), port=args.c66_port, map={})
            threading.Thread(target=mobile.run, daemon=True).start()
        if args.open_browser:
            webbrowser.open(f"http://127.0.0.1:{args.port}/inventario/mesa")
        station.run()
    finally:
        if scale_reader is not None:
            scale_reader.close()
        log_shutdown()


if __name__ == "__main__":
    main()
