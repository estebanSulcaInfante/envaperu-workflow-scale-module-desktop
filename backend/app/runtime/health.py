from flask import Blueprint, current_app, jsonify
from pathlib import Path


health_bp = Blueprint("local_health", __name__)


@health_bp.get("/live")
def live():
    return jsonify(
        {
            "status": "LIVE",
            "profile": current_app.config.get("RUNTIME_PROFILE", "DEVELOPMENT"),
            "server": current_app.config.get("RUNTIME_SERVER", "werkzeug"),
            "debug": bool(current_app.debug),
            "reloader": bool(current_app.config.get("USE_RELOADER", False)),
        }
    )


@health_bp.get("/ready")
def ready():
    from app import db
    from app.models.station_identity import StationRuntimeState
    from app.runtime.lifecycle import RuntimeState

    runtime_state = current_app.config.get("RUNTIME_STATE")
    if runtime_state is not None and runtime_state.status != RuntimeState.READY:
        return (
            jsonify(
                {
                    "status": runtime_state.status,
                    "issues": [{"code": f"RUNTIME_{runtime_state.status}"}],
                }
            ),
            503,
        )

    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception as exc:
        db.session.rollback()
        return (
            jsonify(
                {
                    "status": "NOT_READY",
                    "issues": [
                        {
                            "code": "DATABASE_UNAVAILABLE",
                            "detail": str(exc),
                        }
                    ],
                }
            ),
            503,
        )

    issues = []
    expected_schema = current_app.config.get("SCHEMA_VERSION")
    if expected_schema is not None and db.engine.dialect.name == "sqlite":
        try:
            from app.storage.migrations import current_schema_version

            actual_schema = current_schema_version(db.engine)
            if actual_schema != expected_schema:
                issues.append(
                    {
                        "code": "SCHEMA_INCOMPATIBLE",
                        "expected": expected_schema,
                        "actual": actual_schema,
                    }
                )
        except Exception as exc:
            issues.append(
                {
                    "code": "SCHEMA_UNAVAILABLE",
                    "detail": str(exc),
                }
            )

    for directory in current_app.config.get("STATION_STORAGE_DIRECTORIES", []):
        if not Path(directory).is_dir():
            issues.append(
                {
                    "code": "STORAGE_DIRECTORY_UNAVAILABLE",
                    "path": str(directory),
                }
            )

    if issues:
        return jsonify({"status": "NOT_READY", "issues": issues}), 503

    monitoring = StationRuntimeState.query.one_or_none()
    central = (
        monitoring.to_monitoring_dict()
        if monitoring is not None
        else {
            "state": "CENTRAL_NOT_PROVISIONED",
            "last_central_ack_utc": None,
            "last_error_code": None,
        }
    )
    return jsonify({"status": "READY", "issues": [], "central": central})
