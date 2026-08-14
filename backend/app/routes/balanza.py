from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from app.services.scale_service import get_scale_service
from app import socketio

balanza_bp = Blueprint('balanza', __name__)

# Último peso recibido (para endpoint HTTP de fallback)
_last_weight = {
    'peso_kg': None,
    'stable': False,
    'received_at_utc': None,
}


def _on_weight_received(weight: float):
    """Callback cuando se recibe un peso de la balanza - emite via WebSocket"""
    _last_weight['peso_kg'] = weight
    # La balanza piloto entrega el ticket NET después de estabilizar. El
    # backend conserva esa atestación y F2 no acepta un peso enviado por UI.
    _last_weight['stable'] = True
    _last_weight['received_at_utc'] = datetime.now(timezone.utc)
    # Emitir instantáneamente a todos los clientes conectados
    socketio.emit('peso', {'peso_kg': weight})


@balanza_bp.route('/status', methods=['GET'])
def get_status():
    if current_app.config.get('PORTFOLIO_DEMO_MODE'):
        return jsonify({
            'port': 'SIMULADA',
            'baud_rate': None,
            'connected': True,
            'listening': True,
            'simulation_enabled': True,
            'portfolio_demo': True,
        })
    """Obtiene el estado de la conexión con la balanza"""
    service = get_scale_service()
    return jsonify({
        **service.get_status(),
        'simulation_enabled': bool(
            current_app.config.get('ALLOW_SCALE_SIMULATION')
        ),
    })


@balanza_bp.route('/simular-peso', methods=['POST'])
def simular_peso():
    """Inyecta una lectura estable solo en estaciones locales habilitadas."""
    if not current_app.config.get('ALLOW_SCALE_SIMULATION'):
        return jsonify({
            'status': 'error',
            'code': 'SCALE_SIMULATION_DISABLED',
            'error': 'La simulación de balanza no está habilitada.',
        }), 403
    data = request.get_json(silent=True) or {}
    try:
        weight = float(data.get('peso_kg'))
    except (TypeError, ValueError):
        return jsonify({
            'status': 'error',
            'code': 'INVALID_SIMULATED_WEIGHT',
            'error': 'peso_kg debe ser un número.',
        }), 422
    max_weight = float(current_app.config.get('MAX_CAPTURE_WEIGHT_KG', 1000))
    if weight <= 0 or weight > max_weight:
        return jsonify({
            'status': 'error',
            'code': 'INVALID_SIMULATED_WEIGHT',
            'error': f'peso_kg debe ser mayor que cero y menor o igual a {max_weight}.',
        }), 422
    _on_weight_received(round(weight, 3))
    socketio.emit('balanza_status', {
        'connected': True,
        'listening': True,
        'port': 'SIMULADA',
        'simulated': True,
    })
    return jsonify({
        'status': 'ok',
        'peso_kg': _last_weight['peso_kg'],
        'stable': True,
        'simulated': True,
    })


@balanza_bp.route('/conectar', methods=['POST'])
def conectar():
    if current_app.config.get('PORTFOLIO_DEMO_MODE'):
        return jsonify({
            'status': 'ok',
            'connected': True,
            'listening': True,
            'port': 'SIMULADA',
            'simulated': True,
        })
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
    if current_app.config.get('PORTFOLIO_DEMO_MODE'):
        return jsonify({
            'status': 'ok',
            'connected': True,
            'listening': True,
            'port': 'SIMULADA',
            'simulated': True,
        })
    """Desconecta de la balanza"""
    service = get_scale_service()
    service.disconnect()
    _last_weight['peso_kg'] = None
    _last_weight['stable'] = False
    _last_weight['received_at_utc'] = None
    socketio.emit('balanza_status', {'connected': False, 'listening': False, 'port': service.port})
    return jsonify({'status': 'ok', 'connected': False})


@balanza_bp.route('/iniciar-escucha', methods=['POST'])
def iniciar_escucha():
    if current_app.config.get('PORTFOLIO_DEMO_MODE'):
        return jsonify({
            'status': 'ok',
            'listening': True,
            'connected': True,
            'port': 'SIMULADA',
            'simulated': True,
        })
    """Inicia la escucha continua de la balanza"""
    _last_weight['peso_kg'] = None
    _last_weight['stable'] = False
    _last_weight['received_at_utc'] = None
    
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
    if current_app.config.get('PORTFOLIO_DEMO_MODE'):
        return jsonify({
            'status': 'ok',
            'listening': True,
            'connected': True,
            'port': 'SIMULADA',
            'simulated': True,
        })
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
        'peso_kg': _last_weight['peso_kg'],
        'stable': _last_weight['stable'],
        'received_at_utc': (
            _last_weight['received_at_utc'].isoformat()
            if _last_weight['received_at_utc'] else None
        ),
    })


def get_last_scale_snapshot():
    return dict(_last_weight)

