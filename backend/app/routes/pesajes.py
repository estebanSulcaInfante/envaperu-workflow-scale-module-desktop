from datetime import datetime, date
from flask import Blueprint, request, jsonify
from app import db
from app.models.pesaje import Pesaje
from app.services.sticker_service import get_sticker_service

pesajes_bp = Blueprint('pesajes', __name__)


@pesajes_bp.route('', methods=['GET'])
def listar_pesajes():
    """Lista todos los pesajes con paginación"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    pesajes = Pesaje.query.order_by(Pesaje.fecha_hora.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return jsonify({
        'items': [p.to_dict() for p in pesajes.items],
        'total': pesajes.total,
        'page': pesajes.page,
        'pages': pesajes.pages
    })


@pesajes_bp.route('', methods=['POST'])
def crear_pesaje():
    """Crea un nuevo registro de pesaje"""
    data = request.get_json()
    
    if not data or 'peso_kg' not in data:
        return jsonify({'error': 'peso_kg es requerido'}), 400
    
    # Parse fecha_orden_trabajo si viene como string
    fecha_ot = None
    if data.get('fecha_orden_trabajo'):
        try:
            fecha_ot = datetime.strptime(data['fecha_orden_trabajo'], '%Y-%m-%d').date()
        except ValueError:
            pass
    
    pesaje = Pesaje(
        peso_kg=data['peso_kg'],
        molde=data.get('molde'),
        maquina=data.get('maquina'),
        nro_op=data.get('nro_op'),
        turno=data.get('turno'),
        fecha_orden_trabajo=fecha_ot,
        nro_orden_trabajo=data.get('nro_orden_trabajo'),
        operador=data.get('operador'),
        color=data.get('color'),
        observaciones=data.get('observaciones'),
        qr_data_original=data.get('qr_data_original')
    )
    
    db.session.add(pesaje)
    db.session.commit()
    
    return jsonify(pesaje.to_dict()), 201


@pesajes_bp.route('/parse-qr', methods=['POST'])
def parse_qr():
    """
    Parsea el contenido de un QR escaneado.
    Formato: "398;CERNIDOR ROMANO;HT-250B;OP1354;DIURNO;2026-01-03;0000"
    """
    data = request.get_json()
    qr_string = data.get('qr_data', '')
    
    if not qr_string:
        return jsonify({'error': 'qr_data es requerido'}), 400
    
    parsed = Pesaje.parse_qr_data(qr_string)
    
    if not parsed:
        return jsonify({'error': 'Formato de QR inválido'}), 400
    
    return jsonify({
        'status': 'ok',
        'data': parsed
    })


@pesajes_bp.route('/<int:id>', methods=['GET'])
def obtener_pesaje(id):
    """Obtiene un pesaje por ID"""
    pesaje = Pesaje.query.get_or_404(id)
    return jsonify(pesaje.to_dict())


@pesajes_bp.route('/<int:id>', methods=['PUT'])
def actualizar_pesaje(id):
    """Actualiza un pesaje existente"""
    pesaje = Pesaje.query.get_or_404(id)
    data = request.get_json()
    
    if 'peso_kg' in data:
        pesaje.peso_kg = data['peso_kg']
    if 'molde' in data:
        pesaje.molde = data['molde']
    if 'maquina' in data:
        pesaje.maquina = data['maquina']
    if 'nro_op' in data:
        pesaje.nro_op = data['nro_op']
    if 'turno' in data:
        pesaje.turno = data['turno']
    if 'nro_orden_trabajo' in data:
        pesaje.nro_orden_trabajo = data['nro_orden_trabajo']
    if 'color' in data:
        pesaje.color = data['color']
    if 'operador' in data:
        pesaje.operador = data['operador']
    if 'observaciones' in data:
        pesaje.observaciones = data['observaciones']
    if 'fecha_orden_trabajo' in data and data['fecha_orden_trabajo']:
        try:
            pesaje.fecha_orden_trabajo = datetime.strptime(
                data['fecha_orden_trabajo'], '%Y-%m-%d'
            ).date()
        except ValueError:
            pass
    
    db.session.commit()
    return jsonify(pesaje.to_dict())


@pesajes_bp.route('/<int:id>', methods=['DELETE'])
def eliminar_pesaje(id):
    """Elimina un pesaje"""
    pesaje = Pesaje.query.get_or_404(id)
    db.session.delete(pesaje)
    db.session.commit()
    return '', 204


@pesajes_bp.route('/<int:id>/imprimir', methods=['POST'])
def imprimir_sticker(id):
    """Imprime el sticker de un pesaje"""
    pesaje = Pesaje.query.get_or_404(id)
    
    sticker_service = get_sticker_service()
    success = sticker_service.print_sticker(pesaje)
    
    if success:
        pesaje.sticker_impreso = True
        pesaje.fecha_impresion = datetime.utcnow()
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Sticker enviado a impresión'})
    else:
        return jsonify({'status': 'error', 'message': 'Error al imprimir'}), 500


@pesajes_bp.route('/<int:id>/preview-sticker', methods=['GET'])
def preview_sticker(id):
    """Obtiene preview del sticker en texto"""
    pesaje = Pesaje.query.get_or_404(id)
    
    sticker_service = get_sticker_service()
    preview = sticker_service.generate_sticker_text(pesaje)
    
    return jsonify({
        'preview': preview,
        'qr_data': pesaje.generate_sticker_qr_data()
    })


@pesajes_bp.route('/sin-sincronizar', methods=['GET'])
def pesajes_sin_sincronizar():
    """Obtiene pesajes pendientes de sincronización con API central"""
    pesajes = Pesaje.query.filter_by(sincronizado=False).all()
    return jsonify([p.to_dict() for p in pesajes])


@pesajes_bp.route('/marcar-sincronizado', methods=['POST'])
def marcar_sincronizado():
    """Marca pesajes como sincronizados"""
    data = request.get_json()
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'error': 'ids es requerido'}), 400
    
    Pesaje.query.filter(Pesaje.id.in_(ids)).update({
        'sincronizado': True,
        'fecha_sincronizacion': datetime.utcnow()
    }, synchronize_session=False)
    
    db.session.commit()
    return jsonify({'status': 'ok', 'count': len(ids)})
