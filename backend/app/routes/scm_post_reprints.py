from flask import Blueprint, jsonify
from app.services.scm_post_reprint_service import PostReprintService
from app.services.central_api_client import CentralApiError

scm_post_reprints_bp = Blueprint('scm_post_reprints', __name__)


@scm_post_reprints_bp.errorhandler(ValueError)
def invalid_request(exc):
    return jsonify({'code': 'POST_REPRINT_DISABLED_OR_INVALID', 'message': str(exc)}), 409


@scm_post_reprints_bp.errorhandler(CentralApiError)
def unavailable(exc):
    return jsonify({'code': exc.state, 'message': str(exc)}), 503


@scm_post_reprints_bp.get('/scm/post-reprint-jobs')
def list_jobs():
    return jsonify(PostReprintService().list_jobs())


@scm_post_reprints_bp.post('/scm/post-reprint-jobs/<uuid:job_id>/print')
def print_copy(job_id):
    return jsonify(PostReprintService().execute(str(job_id)))


@scm_post_reprints_bp.post('/scm/post-reprint-jobs/sync-evidence')
def sync_evidence():
    return jsonify(PostReprintService().sync_evidence())
