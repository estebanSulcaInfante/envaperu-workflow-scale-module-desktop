from flask import Blueprint, jsonify, request

from app.services.central_api_client import CentralApiError
from app.services.scm_prepared_material_service import get_scm_prepared_material_weighing_service
from app.services.scm_weighing_service import ScmWeighingLocalError


scm_prepared_material_bp = Blueprint("scm_prepared_material", __name__)


@scm_prepared_material_bp.post("/scm/prepared-material/capture")
def capture_prepared_material():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_scm_prepared_material_weighing_service().capture(
            operation_id=request.headers.get("Idempotency-Key"),
            target_qr=data.get("target_qr"), tara_kg=data.get("tara_kg", "0"),
        ))
    except CentralApiError as exc:
        return jsonify({"code": exc.state, "message": str(exc)}), 503
    except ScmWeighingLocalError as exc:
        return jsonify({"code": exc.code, "message": exc.message}), exc.status


@scm_prepared_material_bp.post("/scm/prepared-material/source-units/resolve")
def resolve_prepared_material_source():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_scm_prepared_material_weighing_service().resolve_source(
            target_qr=data.get("target_qr"), source_qr=data.get("source_qr"),
        ))
    except CentralApiError as exc:
        return jsonify({"code": exc.state, "message": str(exc)}), 503
    except ScmWeighingLocalError as exc:
        return jsonify({"code": exc.code, "message": exc.message}), exc.status
