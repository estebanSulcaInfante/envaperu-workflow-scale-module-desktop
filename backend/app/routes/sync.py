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


@sync_bp.route('/moldes', methods=['POST'])
def sync_moldes():
    """
    Sincroniza el catálogo de moldes desde el backend central.
    Descarga moldes y piezas, y los guarda en cache local.
    """
    from datetime import datetime
    import requests
    from app import db
    from app.models.molde_cache import MoldePiezasCache
    from app.config import Config
    
    central_url = Config.CENTRAL_API_URL
    if not central_url:
        return jsonify({'error': 'CENTRAL_API_URL no configurado'}), 400
    
    try:
        # Descargar moldes del API central
        response = requests.get(f"{central_url}/api/moldes/exportar", timeout=10)
        response.raise_for_status()
        moldes = response.json()
        
        # Limpiar cache existente
        MoldePiezasCache.query.delete()
        
        # Insertar nuevos registros
        count = 0
        for molde in moldes:
            for pieza in molde.get('piezas', []):
                cache_entry = MoldePiezasCache(
                    molde_codigo=molde['codigo'],
                    molde_nombre=molde['nombre'],
                    peso_tiro_gr=molde.get('peso_tiro_gr'),
                    tiempo_ciclo_std=molde.get('tiempo_ciclo_std'),
                    pieza_sku=pieza['sku'],
                    pieza_nombre=pieza['nombre'],
                    tipo=pieza.get('tipo', 'SIMPLE'),
                    cavidades=pieza.get('cavidades'),
                    peso_unitario_gr=pieza.get('peso_unitario_gr'),
                    updated_at=datetime.utcnow()
                )
                db.session.add(cache_entry)
                count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Sincronizados {len(moldes)} moldes, {count} piezas',
            'moldes': len(moldes),
            'piezas': count
        })
        
    except requests.RequestException as e:
        return jsonify({'error': f'Error conectando con API central: {str(e)}'}), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@sync_bp.route('/cache/piezas/<molde_nombre>', methods=['GET'])
def get_cached_piezas(molde_nombre):
    """
    Obtiene las piezas cacheadas para un molde específico.
    Busca por nombre de molde (case insensitive).
    """
    from app.models.molde_cache import MoldePiezasCache
    
    piezas = MoldePiezasCache.query.filter(
        MoldePiezasCache.molde_nombre.ilike(f'%{molde_nombre}%')
    ).all()
    
    return jsonify([p.to_dict() for p in piezas])
