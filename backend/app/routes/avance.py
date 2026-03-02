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
    Retorna pesajes de hoy agrupados por molde+color.
    Estructura: { grupos: [ { molde, color, total_kg, total_bolsas, pesajes: [...] }, ... ] }
    """
    today = date.today()
    
    pesajes = Pesaje.query.filter(
        func.date(Pesaje.fecha_hora) == today
    ).order_by(Pesaje.fecha_hora.desc()).all()
    
    # Agrupar por molde + color
    grupos_dict = {}
    total_global_kg = 0.0
    total_registros = 0
    
    for p in pesajes:
        molde = p.molde or 'SIN MOLDE'
        color = p.color or 'SIN COLOR'
        key = f"{molde}|{color}"
        
        if key not in grupos_dict:
            grupos_dict[key] = {
                'molde': molde,
                'color': color,
                'total_kg': 0.0,
                'total_bolsas': 0,
                'pesajes': []
            }
        
        peso = p.peso_kg if p.peso_kg else 0.0
        grupos_dict[key]['total_kg'] += peso
        grupos_dict[key]['total_bolsas'] += 1
        grupos_dict[key]['pesajes'].append({
            'id': p.id,
            'peso_kg': p.peso_kg,
            'fecha_hora': p.fecha_hora.isoformat() if p.fecha_hora else None,
            'nro_op': p.nro_op,
            'nro_orden_trabajo': p.nro_orden_trabajo,
        })
        
        total_global_kg += peso
        total_registros += 1
    
    # Convertir a lista y redondear
    grupos = list(grupos_dict.values())
    for g in grupos:
        g['total_kg'] = round(g['total_kg'], 2)
    
    # Ordenar por peso total descendente
    grupos.sort(key=lambda x: x['total_kg'], reverse=True)
    
    return jsonify({
        'fecha': today.isoformat(),
        'grupos': grupos,
        'total_global_kg': round(total_global_kg, 2),
        'total_registros': total_registros
    })
