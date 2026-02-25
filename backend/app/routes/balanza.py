from flask import Blueprint, jsonify
from collections import deque
from app.services.scale_service import get_scale_service

balanza_bp = Blueprint('balanza', __name__)

# Cola de pesos capturados en tiempo real (thread-safe con deque)
_weight_queue = deque(maxlen=10)


def _on_weight_received(weight: float):
    """Callback cuando se recibe un peso de la balanza"""
    _weight_queue.append(weight)


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
    
    if not success:
        return jsonify({
            'status': 'error',
            'connected': False,
            'error': f'No se pudo conectar a {service.port}. Verifica que el puerto esté disponible.'
        }), 500
    
    return jsonify({
        'status': 'ok',
        'connected': True,
        'port': service.port
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
    _weight_queue.clear()
    
    service = get_scale_service()
    
    # Verificar que esté conectado primero
    if not service.serial_connection or not service.serial_connection.is_open:
        if not service.connect():
            return jsonify({
                'status': 'error',
                'listening': False,
                'error': f'No se pudo conectar a {service.port}'
            }), 500
    
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
    pesos = list(_weight_queue)
    _weight_queue.clear()
    
    return jsonify({
        'pesos': pesos,
        'count': len(pesos)
    })
