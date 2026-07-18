import uuid

from flask import Blueprint, current_app, jsonify, request

from app import db, socketio
from app.models.pesaje import Pesaje
from app.models.pesaje_correction_request import PesajeCorrectionRequest
from app.services.correction_request_service import (
    CorrectionIdempotencyConflict,
    CorrectionRequestService,
    CorrectionValidationError,
    PesajeAlreadyVoid,
)
from app.services.capture_service import (
    CaptureService,
    CaptureValidationError,
    IdempotencyConflict,
)
from app.services.print_attempt_service import execute_print_attempt


local_capture_bp = Blueprint("local_capture", __name__)


def _capture_id_from_value(raw_value, required=True):
    if not raw_value:
        if required:
            return None, (
                jsonify(
                    {
                        "code": "IDEMPOTENCY_KEY_REQUIRED",
                        "message": "Idempotency-Key es requerido",
                    }
                ),
                400,
            )
        return None, None
    try:
        return str(uuid.UUID(str(raw_value).strip())), None
    except (ValueError, AttributeError, TypeError):
        return None, (
            jsonify(
                {
                    "code": "INVALID_IDEMPOTENCY_KEY",
                    "message": "Idempotency-Key debe ser UUID",
                }
            ),
            400,
        )


@local_capture_bp.post("/pesajes")
def create_local_capture():
    capture_id, error = _capture_id_from_value(
        request.headers.get("Idempotency-Key")
    )
    if error:
        return error
    if not request.is_json:
        return (
            jsonify(
                {
                    "code": "JSON_REQUIRED",
                    "message": "Content-Type application/json es requerido",
                }
            ),
            415,
        )

    payload = request.get_json(silent=True)
    try:
        result = CaptureService().create(
            capture_id=capture_id,
            payload=payload,
            max_weight_kg=current_app.config.get(
                "MAX_CAPTURE_WEIGHT_KG",
                1000.0,
            ),
        )
    except CaptureValidationError as exc:
        return jsonify({"code": exc.code, "message": exc.message}), 422
    except IdempotencyConflict:
        return (
            jsonify(
                {
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": "La clave ya fue usada con otro payload",
                    "capture_id": capture_id,
                }
            ),
            409,
        )

    if result.created:
        socketio.emit("pesajes_updated")
    response = jsonify(
        {
            "status": result.pesaje.print_status,
            "idempotent_replay": not result.created,
            "pesaje": result.pesaje.to_dict(),
        }
    )
    response.headers["Idempotency-Key"] = capture_id
    return response, 201 if result.created else 200


@local_capture_bp.post("/pesajes/<capture_id>/print")
def print_local_capture(capture_id):
    canonical_id, error = _capture_id_from_value(capture_id)
    if error:
        return error
    pesaje = Pesaje.query.filter_by(capture_id=canonical_id).one_or_none()
    if pesaje is None:
        return (
            jsonify(
                {
                    "code": "CAPTURE_NOT_FOUND",
                    "message": "No existe el pesaje para capture_id",
                }
            ),
            404,
        )

    outcome = execute_print_attempt(pesaje)
    socketio.emit("pesajes_updated")
    return jsonify(
        {
            "status": outcome.status,
            "pesaje": pesaje.to_dict(),
            "print_attempt": outcome.attempt.to_dict(),
        }
    )


@local_capture_bp.post("/pesajes/<int:pesaje_id>/corrections")
def create_correction_request(pesaje_id):
    request_id, error = _capture_id_from_value(
        request.headers.get("Idempotency-Key")
    )
    if error:
        return error
    if not request.is_json:
        return (
            jsonify(
                {
                    "code": "JSON_REQUIRED",
                    "message": "Content-Type application/json es requerido",
                }
            ),
            415,
        )

    pesaje = db.get_or_404(Pesaje, pesaje_id)
    try:
        result = CorrectionRequestService().create(
            request_id=request_id,
            pesaje=pesaje,
            payload=request.get_json(silent=True),
            max_weight_kg=current_app.config.get(
                "MAX_CAPTURE_WEIGHT_KG",
                1000.0,
            ),
        )
    except CorrectionValidationError as exc:
        return jsonify({"code": exc.code, "message": exc.message}), 422
    except CorrectionIdempotencyConflict:
        return (
            jsonify(
                {
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": "La clave ya fue usada con otra solicitud",
                    "request_id": request_id,
                }
            ),
            409,
        )
    except PesajeAlreadyVoid:
        return (
            jsonify(
                {
                    "code": "PESAJE_ALREADY_VOID",
                    "message": "El pesaje ya esta clasificado como anulado local",
                }
            ),
            409,
        )

    if result.created:
        socketio.emit("pesajes_updated")
    response = jsonify(
        {
            "idempotent_replay": not result.created,
            "correction_request": result.request.to_dict(),
            "pesaje": pesaje.to_dict(),
        }
    )
    response.headers["Idempotency-Key"] = request_id
    return response, 201 if result.created else 200


@local_capture_bp.get("/pesajes/<int:pesaje_id>/corrections")
def list_correction_requests(pesaje_id):
    pesaje = db.get_or_404(Pesaje, pesaje_id)
    items = PesajeCorrectionRequest.query.filter_by(pesaje_id=pesaje_id).order_by(
        PesajeCorrectionRequest.id
    ).all()
    return jsonify(
        {
            "items": [item.to_dict() for item in items],
            "pesaje": pesaje.to_dict(),
        }
    )
