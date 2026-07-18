from pathlib import Path

from flask import abort, send_from_directory


RESERVED_PREFIXES = ("api", "socket.io")


def _index_response(static_dir):
    response = send_from_directory(static_dir, "index.html")
    response.headers["Cache-Control"] = "no-store"
    return response


def register_static_ui(app, static_dir):
    resolved_static_dir = Path(static_dir).resolve()
    index_path = resolved_static_dir / "index.html"
    assets_dir = resolved_static_dir / "assets"

    if not index_path.is_file():
        raise RuntimeError(f"Compiled frontend not found: {index_path}")

    @app.get("/")
    def station_index():
        return _index_response(resolved_static_dir)

    @app.get("/assets/<path:filename>")
    def station_asset(filename):
        if not assets_dir.is_dir():
            abort(404)
        response = send_from_directory(assets_dir, filename)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    @app.get("/<path:ui_path>")
    def station_spa(ui_path):
        first_segment = ui_path.split("/", 1)[0]
        if first_segment in RESERVED_PREFIXES:
            abort(404)

        candidate = resolved_static_dir / ui_path
        if candidate.is_file():
            response = send_from_directory(resolved_static_dir, ui_path)
            response.headers["Cache-Control"] = "no-cache"
            return response

        return _index_response(resolved_static_dir)

