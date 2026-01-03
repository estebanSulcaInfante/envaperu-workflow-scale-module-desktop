from flask import Blueprint, jsonify
from app.services.scale_service import get_scale_service

balanza_bp = Blueprint('balanza', __name__)

# Cola de pesos capturados en tiempo real
_weight_queue = []


def _on_weight_received(weight: float):
    """Callback cuando se recibe un peso de la balanza"""
    global _weight_queue
    _weight_queue.append(weight)
    # Mantener solo los últimos 10 pesos
    if len(_weight_queue) > 10:
        _weight_queue.pop(0)


@balanza_bp.route('/status', methods=['GET'])
def get_status():
    """Obtiene el estado de la conexión con la balanza"""
    service = get_scale_service()
    return jsonify(service.get_status())


@balanza_bp.route('/conectar', methods=['POST'])
def conectar():
    """Conecta con la balanza"""
    service = get_scale_service()
    success = service.connect()
    return jsonify({
        'status': 'ok' if success else 'error',
        'connected': success
    })


@balanza_bp.route('/desconectar', methods=['POST'])
def desconectar():
    """Desconecta de la balanza"""
    service = get_scale_service()
    service.disconnect()
    return jsonify({'status': 'ok', 'connected': False})


@balanza_bp.route('/iniciar-escucha', methods=['POST'])
def iniciar_escucha():
    """Inicia la escucha continua de la balanza"""
    global _weight_queue
    _weight_queue = []
    
    service = get_scale_service()
    service.start_listening(_on_weight_received)
    
    return jsonify({
        'status': 'ok',
        'listening': True
    })


@balanza_bp.route('/detener-escucha', methods=['POST'])
def detener_escucha():
    """Detiene la escucha de la balanza"""
    service = get_scale_service()
    service.stop_listening()
    
    return jsonify({
        'status': 'ok',
        'listening': False
    })


@balanza_bp.route('/ultimo-peso', methods=['GET'])
def ultimo_peso():
    """Obtiene el último peso capturado"""
    global _weight_queue
    
    if _weight_queue:
        return jsonify({
            'peso_kg': _weight_queue[-1],
            'queue_length': len(_weight_queue)
        })
    else:
        return jsonify({
            'peso_kg': None,
            'queue_length': 0
        })


@balanza_bp.route('/pesos-pendientes', methods=['GET'])
def pesos_pendientes():
    """Obtiene todos los pesos pendientes en la cola"""
    global _weight_queue
    pesos = list(_weight_queue)
    _weight_queue = []  # Limpiar cola
    
    return jsonify({
        'pesos': pesos,
        'count': len(pesos)
    })
