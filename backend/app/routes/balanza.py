from flask import Blueprint, jsonify
from app.services.scale_service import get_scale_service
from app import socketio

balanza_bp = Blueprint('balanza', __name__)

# Último peso recibido (para endpoint HTTP de fallback)
_last_weight = {'peso_kg': None}


def _on_weight_received(weight: float):
    """Callback cuando se recibe un peso de la balanza - emite via WebSocket"""
    _last_weight['peso_kg'] = weight
    # Emitir instantáneamente a todos los clientes conectados
    socketio.emit('peso', {'peso_kg': weight})


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
        socketio.emit('balanza_status', {'connected': False, 'listening': False, 'port': service.port})
        return jsonify({
            'status': 'error',
            'connected': False,
            'error': f'No se pudo conectar a {service.port}. Verifica que el puerto esté disponible.'
        }), 500
    
    socketio.emit('balanza_status', {'connected': True, 'listening': False, 'port': service.port})
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
    _last_weight['peso_kg'] = None
    socketio.emit('balanza_status', {'connected': False, 'listening': False, 'port': service.port})
    return jsonify({'status': 'ok', 'connected': False})


@balanza_bp.route('/iniciar-escucha', methods=['POST'])
def iniciar_escucha():
    """Inicia la escucha continua de la balanza"""
    _last_weight['peso_kg'] = None
    
    service = get_scale_service()
    
    # Verificar que esté conectado primero
    if not service.serial_connection or not service.serial_connection.is_open:
        if not service.connect():
            return jsonify({
                'status': 'error',
                'listening': False,
                'error': f'No se pudo conectar a {service.port}'
            }), 500
    
    service.start_listening(_on_weight_received, socketio=socketio)
    
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
    """Obtiene el último peso capturado (fallback HTTP)"""
    return jsonify({
        'peso_kg': _last_weight['peso_kg']
    })

