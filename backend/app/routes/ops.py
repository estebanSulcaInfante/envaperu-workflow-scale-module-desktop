from flask import Blueprint, request, jsonify
from sqlalchemy import func
from app import db
from app.models.pesaje import Pesaje
from app.models.op_cerrada import OpCerrada

ops_bp = Blueprint('ops', __name__)


@ops_bp.route('/activas', methods=['GET'])
def listar_ops_activas():
    """
    Lista OPs únicas que tienen pesajes, excluyendo las cerradas.
    Agrupa por nro_op y muestra totales.
    """
    # Subquery: OPs cerradas
    cerradas_subq = db.session.query(OpCerrada.nro_op).subquery()
    
    # Query: agrupar pesajes por nro_op, excluyendo cerradas
    resultados = db.session.query(
        Pesaje.nro_op,
        func.max(Pesaje.molde).label('molde'),
        func.sum(Pesaje.peso_kg).label('total_kg'),
        func.count(Pesaje.id).label('total_bolsas'),
        func.max(Pesaje.fecha_hora).label('ultimo_pesaje')
    ).filter(
        Pesaje.nro_op.isnot(None),
        Pesaje.nro_op != '',
        Pesaje.nro_op.notin_(cerradas_subq),
        Pesaje.deleted_at.is_(None)
    ).group_by(Pesaje.nro_op).order_by(func.max(Pesaje.fecha_hora).desc()).all()
    
    ops = []
    for r in resultados:
        ops.append({
            'nro_op': r.nro_op,
            'molde': r.molde,
            'total_kg': round(r.total_kg or 0, 2),
            'total_bolsas': r.total_bolsas,
            'ultimo_pesaje': r.ultimo_pesaje.isoformat() if r.ultimo_pesaje else None,
        })
    
    return jsonify(ops)


@ops_bp.route('/cerradas', methods=['GET'])
def listar_ops_cerradas():
    """Lista todas las OPs que han sido cerradas localmente."""
    cerradas = OpCerrada.query.order_by(OpCerrada.fecha_cierre.desc()).all()
    
    # Enriquecer con totales de pesajes
    resultado = []
    for op in cerradas:
        stats = db.session.query(
            func.sum(Pesaje.peso_kg).label('total_kg'),
            func.count(Pesaje.id).label('total_bolsas')
        ).filter(Pesaje.nro_op == op.nro_op, Pesaje.deleted_at.is_(None)).first()
        
        resultado.append({
            **op.to_dict(),
            'total_kg': round(stats.total_kg or 0, 2) if stats else 0,
            'total_bolsas': stats.total_bolsas if stats else 0,
        })
    
    return jsonify(resultado)


@ops_bp.route('/cerrar', methods=['POST'])
def cerrar_op():
    """Cierra una OP para que no aparezca en el avance."""
    data = request.get_json()
    nro_op = data.get('nro_op')
    
    if not nro_op:
        return jsonify({'error': 'nro_op es requerido'}), 400
    
    # Verificar si ya está cerrada
    existente = OpCerrada.query.filter_by(nro_op=nro_op).first()
    if existente:
        return jsonify({'error': f'OP {nro_op} ya está cerrada'}), 400
    
    op_cerrada = OpCerrada(
        nro_op=nro_op,
        molde=data.get('molde'),
        motivo=data.get('motivo', ''),
    )
    
    db.session.add(op_cerrada)
    db.session.commit()
    
    return jsonify(op_cerrada.to_dict()), 201


@ops_bp.route('/reabrir', methods=['POST'])
def reabrir_op():
    """Reabre una OP cerrada para que vuelva a aparecer en el avance."""
    data = request.get_json()
    nro_op = data.get('nro_op')
    
    if not nro_op:
        return jsonify({'error': 'nro_op es requerido'}), 400
    
    op_cerrada = OpCerrada.query.filter_by(nro_op=nro_op).first()
    if not op_cerrada:
        return jsonify({'error': f'OP {nro_op} no está cerrada'}), 404
    
    db.session.delete(op_cerrada)
    db.session.commit()
    
    return jsonify({'status': 'ok', 'nro_op': nro_op})
