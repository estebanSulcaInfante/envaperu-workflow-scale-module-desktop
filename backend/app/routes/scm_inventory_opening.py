from flask import Blueprint, jsonify, request

from app.services.central_api_client import CentralApiError
from app.services.scm_inventory_opening_service import get_scm_inventory_opening_service
from app.services.scm_inventory_label_service import (
    InventoryLabelError,
    get_scm_inventory_label_service,
)
from app.services.scm_weighing_service import ScmWeighingLocalError


scm_inventory_opening_bp = Blueprint("scm_inventory_opening", __name__)


@scm_inventory_opening_bp.post("/scm/inventory-opening/capture")
def capture_inventory_opening():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_scm_inventory_opening_service().capture(
            operation_id=request.headers.get("Idempotency-Key"),
            target_qr=data.get("target_qr"),
            tara_kg=data.get("tara_kg", "0"),
        ))
    except CentralApiError as exc:
        return jsonify({"code": exc.state, "message": str(exc)}), 503
    except ScmWeighingLocalError as exc:
        return jsonify({"code": exc.code, "message": exc.message}), exc.status


@scm_inventory_opening_bp.post("/scm/inventory-opening/resolve")
def resolve_inventory_opening():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_scm_inventory_opening_service().resolve(
            target_qr=data.get("target_qr"),
        ))
    except CentralApiError as exc:
        return jsonify({"code": exc.state, "message": str(exc)}), 503
    except ScmWeighingLocalError as exc:
        return jsonify({"code": exc.code, "message": exc.message}), exc.status


@scm_inventory_opening_bp.post("/scm/inventory-opening/labels/preview")
def preview_inventory_opening_label():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_scm_inventory_label_service().preview(data.get("unit")))
    except InventoryLabelError as exc:
        return jsonify({"code": exc.code, "message": exc.message}), exc.status


@scm_inventory_opening_bp.post("/scm/inventory-opening/labels/print")
def print_inventory_opening_label():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(get_scm_inventory_label_service().print_label(
            data.get("unit"),
            operation_id=request.headers.get("Idempotency-Key"),
        ))
    except InventoryLabelError as exc:
        return jsonify({"code": exc.code, "message": exc.message}), exc.status
