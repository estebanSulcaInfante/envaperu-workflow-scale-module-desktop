from flask import Blueprint, jsonify, request

from app.services.central_api_client import CentralApiError
from app.services.scm_prelabel_service import get_scm_prelabel_service


scm_prelabels_bp = Blueprint("scm_prelabels", __name__)


@scm_prelabels_bp.get("/scm/print-jobs")
def list_scm_print_jobs():
    status = str(request.args.get("status", "PENDING")).strip().upper()
    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        return jsonify({
            "code": "INVALID_LIMIT",
            "message": "El limite debe ser numerico.",
        }), 400
    if status not in {"PENDING", "PARTIAL", "PRINTED", "FAILED", "ALL"}:
        return jsonify({
            "code": "INVALID_PRINT_JOB_STATUS",
            "message": "El estado de bandeja no es valido.",
        }), 400
    if not 1 <= limit <= 100:
        return jsonify({
            "code": "INVALID_LIMIT",
            "message": "El limite debe estar entre 1 y 100.",
        }), 400
    try:
        return jsonify(
            get_scm_prelabel_service().list_jobs(
                status=status,
                limit=limit,
            )
        )
    except CentralApiError as exc:
        return jsonify({
            "code": exc.state,
            "message": str(exc),
        }), 503


@scm_prelabels_bp.get("/scm/print-jobs/<uuid:print_job_id>")
def preview_scm_print_job(print_job_id):
    try:
        job = get_scm_prelabel_service().fetch(str(print_job_id))
        tspl = get_scm_prelabel_service().generate_tspl(job)
        return jsonify({
            "print_job": job,
            "tspl": tspl,
            "preview_svg": get_scm_prelabel_service().generate_preview_svg(job),
        })
    except CentralApiError as exc:
        return jsonify({
            "code": exc.state,
            "message": str(exc),
        }), 503


@scm_prelabels_bp.post("/scm/print-jobs/<uuid:print_job_id>/print")
def print_scm_print_job(print_job_id):
    try:
        return jsonify(
            get_scm_prelabel_service().print_job(str(print_job_id))
        )
    except CentralApiError as exc:
        return jsonify({
            "code": exc.state,
            "message": str(exc),
        }), 503
