"""
Rutas de sincronización con el backend central.
"""
from flask import Blueprint, jsonify, request

sync_bp = Blueprint('sync', __name__, url_prefix='/api/sync')


@sync_bp.route('/status', methods=['GET'])
def sync_status():
    """
    Retorna el estado de sincronización:
    - Conectividad con el backend central
    - Cantidad de pesajes pendientes
    - Cantidad sincronizados
    """
    from app.services.sync_service import get_sync_service
    
    service = get_sync_service()
    status = service.get_status()
    
    # Check connectivity
    status['connected'] = service.check_connectivity()
    
    return jsonify(status)


@sync_bp.route('/trigger', methods=['POST'])
def trigger_sync():
    """
    Dispara sincronización manual de pesajes pendientes.
    
    Response:
    {
        "success": true,
        "message": "Sincronizados X pesajes",
        "synced": [...],
        "errors": [...]
    }
    """
    from app.services.sync_service import get_sync_service
    
    service = get_sync_service()
    result = service.sync_pesajes()
    
    return jsonify(result), 200 if result.get('success') else 500


@sync_bp.route('/pending', methods=['GET'])
def list_pending():
    """
    Lista pesajes pendientes de sincronización.
    """
    from app.services.sync_service import get_sync_service
    
    service = get_sync_service()
    pesajes = service.get_pending_pesajes()
    
    return jsonify({
        'count': len(pesajes),
        'pesajes': [p.to_dict() for p in pesajes]
    })
