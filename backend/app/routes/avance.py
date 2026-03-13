from flask import Blueprint, jsonify
from app import db
from app.models.pesaje import Pesaje
from app.models.op_cerrada import OpCerrada
from app.utils.logger import get_pesaje_logger

log = get_pesaje_logger()

avance_bp = Blueprint('avance', __name__)

@avance_bp.route('/resumen', methods=['GET'])
def resumen_avance():
    """
    Retorna pesajes agrupados por molde → color (dos niveles).
    Excluye pesajes de OPs cerradas.
    """
    # Obtener OPs cerradas para excluirlas
    ops_cerradas = db.session.query(OpCerrada.nro_op).all()
    ops_cerradas_set = {op.nro_op for op in ops_cerradas}
    
    query = Pesaje.active().order_by(Pesaje.fecha_hora.desc())
    if ops_cerradas_set:
        query = query.filter(
            db.or_(
                Pesaje.nro_op.is_(None),
                Pesaje.nro_op == '',
                Pesaje.nro_op.notin_(ops_cerradas_set)
            )
        )
    pesajes = query.all()
    
    # Agrupar: molde → color → pesajes
    moldes_dict = {}
    total_global_kg = 0.0
    total_registros = 0
    
    for p in pesajes:
        molde = p.molde or 'SIN MOLDE'
        color = p.color or 'SIN COLOR'
        
        if molde not in moldes_dict:
            moldes_dict[molde] = {
                'molde': molde,
                'total_kg': 0.0,
                'total_bolsas': 0,
                'colores_dict': {}
            }
        
        molde_group = moldes_dict[molde]
        
        if color not in molde_group['colores_dict']:
            molde_group['colores_dict'][color] = {
                'color': color,
                'total_kg': 0.0,
                'total_bolsas': 0,
                'pesajes': []
            }
        
        peso = p.peso_kg if p.peso_kg else 0.0
        color_group = molde_group['colores_dict'][color]
        color_group['total_kg'] += peso
        color_group['total_bolsas'] += 1
        color_group['pesajes'].append({
            'id': p.id,
            'peso_kg': p.peso_kg,
            'fecha_hora': p.fecha_hora.isoformat() if p.fecha_hora else None,
            'nro_op': p.nro_op,
            'nro_orden_trabajo': p.nro_orden_trabajo,
        })
        
        molde_group['total_kg'] += peso
        molde_group['total_bolsas'] += 1
        total_global_kg += peso
        total_registros += 1
    
    # Convertir a listas, redondear y ordenar
    grupos_por_molde = []
    for molde_group in moldes_dict.values():
        colores = list(molde_group.pop('colores_dict').values())
        for c in colores:
            c['total_kg'] = round(c['total_kg'], 2)
        colores.sort(key=lambda x: x['total_kg'], reverse=True)
        molde_group['colores'] = colores
        molde_group['total_kg'] = round(molde_group['total_kg'], 2)
        grupos_por_molde.append(molde_group)
    
    grupos_por_molde.sort(key=lambda x: x['total_kg'], reverse=True)
    
    return jsonify({
        'grupos_por_molde': grupos_por_molde,
        'total_global_kg': round(total_global_kg, 2),
        'total_registros': total_registros
    })
