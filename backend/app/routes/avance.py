from flask import Blueprint, jsonify
from sqlalchemy import func
from datetime import date
from app import db
from app.models.pesaje import Pesaje
from app.utils.logger import get_pesaje_logger

log = get_pesaje_logger()

avance_bp = Blueprint('avance', __name__)

@avance_bp.route('/resumen', methods=['GET'])
def resumen_avance():
    """
    Retorna el peso total acumulado y conteo de pesajes hoy,
    agrupado por nro_orden_trabajo o nro_op.
    Solo considera pesajes creados hoy para el dashboard activo.
    """
    today = date.today()
    
    # Query para agrupar pesajes de hoy
    results = db.session.query(
        Pesaje.nro_orden_trabajo,
        Pesaje.nro_op,
        Pesaje.molde,
        Pesaje.maquina,
        Pesaje.turno,
        Pesaje.peso_unitario_teorico,
        func.count(Pesaje.id).label('total_pesajes'),
        func.sum(Pesaje.peso_kg).label('total_peso_kg')
    ).filter(
        func.date(Pesaje.fecha_hora) == today
    ).group_by(
        Pesaje.nro_orden_trabajo,
        Pesaje.nro_op,
        Pesaje.molde,
        Pesaje.maquina,
        Pesaje.turno,
        Pesaje.peso_unitario_teorico
    ).order_by(
        func.sum(Pesaje.peso_kg).desc()
    ).all()
    
    # Formatear la respuesta
    avance_list = []
    total_global_kg = 0.0
    
    for row in results:
        # Calcular unidades estimadas si hay peso unitario (> 0)
        unidades_estimadas = 0
        peso_unit_kg = None
        if row.peso_unitario_teorico and row.peso_unitario_teorico > 0:
            peso_unit_kg = row.peso_unitario_teorico / 1000.0 if row.peso_unitario_teorico > 10 else row.peso_unitario_teorico
            if row.total_peso_kg and peso_unit_kg > 0:
                unidades_estimadas = int(row.total_peso_kg / peso_unit_kg)
        
        peso_total = row.total_peso_kg if row.total_peso_kg else 0.0
        total_global_kg += peso_total
        
        avance_list.append({
            'nro_orden_trabajo': row.nro_orden_trabajo,
            'nro_op': row.nro_op,
            'molde': row.molde,
            'maquina': row.maquina,
            'turno': row.turno,
            'peso_unitario_teorico': row.peso_unitario_teorico,
            'total_pesajes': row.total_pesajes,
            'total_peso_kg': round(peso_total, 2),
            'unidades_estimadas': unidades_estimadas
        })
        
    return jsonify({
        'fecha': today.isoformat(),
        'items': avance_list,
        'total_global_kg': round(total_global_kg, 2),
        'total_registros': sum(r['total_pesajes'] for r in avance_list)
    })
