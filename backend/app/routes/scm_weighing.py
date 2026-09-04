from flask import Blueprint, jsonify, request

from app.services.central_api_client import CentralApiError
from app.services.scm_weighing_service import (
    ScmWeighingLocalError,
    get_scm_weighing_service,
)


scm_weighing_bp = Blueprint("scm_weighing", __name__)


def _error(exc):
    if isinstance(exc, CentralApiError):
        return jsonify({"code": exc.state, "message": str(exc)}), 503
    return jsonify({"code": exc.code, "message": exc.message}), exc.status


@scm_weighing_bp.post("/scm/weighing/resolve")
def resolve_scm_weighing():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            get_scm_weighing_service().resolve(data.get("qr"))
        )
    except (ScmWeighingLocalError, CentralApiError) as exc:
        return _error(exc)


@scm_weighing_bp.post("/scm/weighing/confirm")
def confirm_scm_weighing():
    data = request.get_json(silent=True) or {}
    operation_id = request.headers.get("Idempotency-Key")
    try:
        return jsonify(get_scm_weighing_service().confirm(
            operation_id=operation_id,
            label_id=data.get("label_id"),
            motivo_desfase=data.get("motivo_desfase"),
            cantidad_confirmada_un=data.get("cantidad_confirmada_un"),
            motivo_cierre_parcial=data.get("motivo_cierre_parcial"),
        ))
    except (ScmWeighingLocalError, CentralApiError) as exc:
        return _error(exc)


@scm_weighing_bp.post("/scm/weighing/controls")
def record_scm_weighing_control():
    data = request.get_json(silent=True) or {}
    operation_id = request.headers.get("Idempotency-Key")
    try:
        return jsonify(get_scm_weighing_service().record_control(
            operation_id=operation_id,
            label_id=data.get("label_id"),
        ))
    except (ScmWeighingLocalError, CentralApiError) as exc:
        return _error(exc)


@scm_weighing_bp.get("/scm/weighing/operations/<uuid:operation_id>")
def recover_scm_weighing(operation_id):
    try:
        return jsonify(
            get_scm_weighing_service().recover(str(operation_id))
        )
    except (ScmWeighingLocalError, CentralApiError) as exc:
        return _error(exc)
