from flask import Blueprint, jsonify, request, current_app
import requests
from app import db

rdp_bp = Blueprint('rdp', __name__, url_prefix='/api/rdp')


def _get_central_api():
    """Obtiene la URL base del API central (sin /api al final)."""
    url = current_app.config.get('CENTRAL_API_URL', 'http://127.0.0.1:5000/api')
    # Si termina en /api, quitarlo porque los endpoints de talonarios lo agregan
    return url.rstrip('/api') if url.endswith('/api') else url




@rdp_bp.route('/siguiente', methods=['GET'])
def obtener_siguiente_correlativo():
    """
    Obtiene el siguiente correlativo disponible.
    Primero intenta del cache local, luego del central.
    """
    from app.models.correlativo_cache import get_siguiente_local, get_disponibles_count
    
    # Intentar obtener de cache local
    local = get_siguiente_local()
    
    if local:
        return jsonify({
            'siguiente': local.correlativo,
            'fuente': 'local',
            'disponibles_local': get_disponibles_count()
        })
    
    # Si no hay local, intentar del central
    try:
        res = requests.get(f'{_get_central_api()}/api/talonarios/siguiente', timeout=5)
        if res.ok:
            data = res.json()
            data['fuente'] = 'central'
            return jsonify(data)
        else:
            return jsonify({'error': 'No hay correlativos disponibles'}), 404
    except requests.RequestException as e:
        return jsonify({'error': f'Sin conexión y cache local vacío'}), 503


@rdp_bp.route('/generar', methods=['POST'])
def generar_rdp():
    """
    Genera un nuevo RDP usando cache local.
    Auto-repone cache si hay conexión y está bajo el threshold.
    """
    from app.models.correlativo_cache import (
        consumir_local, get_disponibles_count, necesita_reponer
    )
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Faltan datos'}), 400
        
    # Verificar si viene un correlativo manual (Modo Offline)
    correlativo_manual = data.get('correlativo_manual')
    
    if correlativo_manual:
        correlativo = correlativo_manual
    else:
        # 1. Consumir del cache local
        correlativo = consumir_local(
            nro_op=data.get('nro_op'),
            molde=data.get('molde')
        )
        
        # Si no hay correlativos locales, intentar reponer y reintentar
        if correlativo is None:
            reponer_cache()
            correlativo = consumir_local(
                nro_op=data.get('nro_op'),
                molde=data.get('molde')
            )
        
        if correlativo is None:
            return jsonify({
                'error': 'No hay correlativos disponibles (local ni central)'
            }), 503
    
    # 2. Construir datos RDP
    rdp_data = {
        'nro_orden_trabajo': str(correlativo),
        'nro_op': data.get('nro_op', ''),
        'molde': data.get('molde', ''),
        'maquina': data.get('maquina', ''),
        'turno': data.get('turno', ''),
        'fecha_ot': data.get('fecha_ot', ''),
        'operador': data.get('operador', '')
    }
    
    # 3. Generar QR data
    qr_data = build_rdp_qr(rdp_data)
    
    # 4. Imprimir sticker RDP
    impreso = False
    try:
        impreso = print_rdp_sticker(rdp_data)
    except Exception as e:
        print(f"Error imprimiendo sticker RDP: {e}")
    
    # 5. Auto-reponer cache en background si es necesario (solo si no es manual)
    if not correlativo_manual:
        disponibles = get_disponibles_count()
        if necesita_reponer():
            try:
                reponer_cache()
            except Exception as e:
                print(f"Warning: No se pudo reponer cache: {e}")
    
    return jsonify({
        'success': True,
        'correlativo': correlativo,
        'qr_data': qr_data,
        'impreso': impreso,
        'disponibles_local': get_disponibles_count()
    })


@rdp_bp.route('/cache/status', methods=['GET'])
def cache_status():
    """Estado del cache local de correlativos."""
    from app.models.correlativo_cache import (
        get_disponibles_count, get_siguiente_local, CACHE_THRESHOLD
    )
    
    siguiente = get_siguiente_local()
    disponibles = get_disponibles_count()
    
    return jsonify({
        'disponibles': disponibles,
        'siguiente': siguiente.correlativo if siguiente else None,
        'threshold': CACHE_THRESHOLD,
        'necesita_reponer': disponibles <= CACHE_THRESHOLD
    })


@rdp_bp.route('/cache/reponer', methods=['POST'])
def forzar_reponer():
    """Fuerza reposición del cache desde el servidor central."""
    try:
        resultado = reponer_cache()
        return jsonify(resultado)
    except Exception as e:
        return jsonify({'error': str(e)}), 503


@rdp_bp.route('/cache/anular', methods=['POST'])
def anular_correlativo():
    """
    Anula un correlativo (hoja destruida/perdida).
    
    Request:
    {
        "correlativo": 30001,  // opcional, si no se da, anula el siguiente disponible
        "motivo": "Hoja destruida por agua"
    }
    
    Response:
    {
        "success": true,
        "correlativo": 30001,
        "motivo": "Hoja destruida por agua",
        "fecha": "2026-01-15T12:00:00"
    }
    """
    from app.models.correlativo_cache import CorrelativoCache, get_siguiente_local
    
    data = request.get_json() or {}
    motivo = data.get('motivo', 'Sin especificar')
    correlativo_num = data.get('correlativo')
    
    if correlativo_num:
        # Anular correlativo específico
        corr = db.session.get(CorrelativoCache, correlativo_num)
        if not corr:
            return jsonify({'error': f'Correlativo {correlativo_num} no encontrado en cache'}), 404
        if corr.usado and not corr.anulado:
            return jsonify({'error': f'Correlativo {correlativo_num} ya fue usado'}), 400
    else:
        # Anular el siguiente disponible
        corr = get_siguiente_local()
        if not corr:
            return jsonify({'error': 'No hay correlativos disponibles para anular'}), 404
    
    corr.anular(motivo)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'correlativo': corr.correlativo,
        'motivo': corr.motivo_anulacion,
        'fecha': corr.fecha_anulacion.isoformat()
    })


@rdp_bp.route('/cache/anulados', methods=['GET'])
def listar_anulados():
    """Lista todos los correlativos anulados."""
    from app.models.correlativo_cache import CorrelativoCache
    
    anulados = CorrelativoCache.query.filter_by(anulado=True).order_by(
        CorrelativoCache.fecha_anulacion.desc()
    ).all()
    
    return jsonify([c.to_dict() for c in anulados])


def reponer_cache():
    """Repone el cache local desde el servidor central."""
    from app.models.correlativo_cache import agregar_a_cache, CACHE_BATCH_SIZE
    
    try:
        res = requests.post(
            f'{_get_central_api()}/api/talonarios/reservar',
            json={'cantidad': CACHE_BATCH_SIZE},
            timeout=10
        )
        
        if res.ok:
            data = res.json()
            correlativos = data.get('correlativos', [])
            agregados = agregar_a_cache(correlativos)
            
            return {
                'success': True,
                'recibidos': len(correlativos),
                'agregados': agregados
            }
        else:
            return {'success': False, 'error': 'No hay correlativos en central'}
            
    except requests.RequestException as e:
        return {'success': False, 'error': f'Sin conexión: {str(e)}'}


def build_rdp_qr(data: dict, rdp_id: int = 0) -> str:
    """
    Construye el contenido del QR para RDP.
    Formato real: id;molde;maquina;nro_op;turno;fecha;correlativo
    Ejemplo: 367;BALDE REAL;HT-320A;OP1353;Diurno;2025-12-22;023455
    """
    return ';'.join([
        str(rdp_id),
        data.get('molde', ''),
        data.get('maquina', ''),
        data.get('nro_op', ''),
        data.get('turno', ''),
        data.get('fecha_ot', ''),
        data.get('nro_orden_trabajo', '')
    ])


def print_rdp_sticker(data: dict) -> bool:
    """
    Imprime sticker RDP con QR.
    Formato específico para Registro Diario de Producción.
    """
    from app.services.printer_service import get_printer_service
    
    qr_data = build_rdp_qr(data)
    
    # Generar TSPL para sticker RDP
    tspl = generate_rdp_tspl(data, qr_data)
    
    printer = get_printer_service()
    return printer.print_tspl(tspl)


def generate_rdp_tspl(data: dict, qr_data: str) -> str:
    """
    Genera TSPL para sticker de Registro Diario de Producción.
    Formato 2-up en papel de 105mm x 50mm (2 stickers de 5x5cm).
    Mismo layout que el sticker de pesaje.
    """
    nro_ot = data.get('nro_orden_trabajo', '')
    nro_op = data.get('nro_op', '')
    molde = data.get('molde', '')[:25]
    turno = data.get('turno', '')
    fecha = data.get('fecha_ot', '')
    operador = data.get('operador', '')[:25]
    maquina = data.get('maquina', '')

    LEFT_X = 40
    RIGHT_X = 456
    LINE_HEIGHT = 18

    def gen_sticker(x: int) -> str:
        """Genera TSPL para un sticker RDP en posición x."""
        y = 20
        lines = []

        # Barra superior gruesa
        lines.append(f'BAR {x}, {y}, 360, 3')
        y += 8

        # Título
        lines.append(f'TEXT {x + 4}, {y}, "2", 0, 1, 1, "REG. DIARIO PROD."')
        y += 28

        # Separador
        lines.append(f'BAR {x}, {y}, 360, 2')
        y += 5

        # Campos
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "NrOT: {nro_ot}"')
        y += LINE_HEIGHT
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "NrOP: {nro_op}"')
        y += LINE_HEIGHT
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "MOL: {molde}"')
        y += LINE_HEIGHT
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "MAQ: {maquina}"')
        y += LINE_HEIGHT
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "TUR: {turno}"')
        y += LINE_HEIGHT
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "FECHA: {fecha}"')
        y += LINE_HEIGHT
        lines.append(f'TEXT {x + 4}, {y}, "1", 0, 1, 1, "OPE: {operador}"')
        y += LINE_HEIGHT

        # Separador QR
        lines.append(f'BAR {x}, {y}, 360, 2')
        y += 5

        # QR Code centrado dentro del sticker (nivel 5 para mayor tamaño)
        lines.append(f'QRCODE {x + 90}, {y}, L, 5, A, 0, "{qr_data}"')
        y += 155

        # Barra final gruesa (alineada con sticker pesaje ~y=350)
        lines.append(f'BAR {x}, {y}, 360, 3')

        return '\n'.join(lines)

    tspl = f"""
SIZE 109 mm, 50 mm
GAP 3 mm, 0 mm
SET REFERENCE 0,0
DIRECTION 1
HOME
CLS

; === STICKER IZQUIERDO ===
{gen_sticker(LEFT_X)}

; === STICKER DERECHO ===
{gen_sticker(RIGHT_X)}

PRINT 1,1
"""
    return tspl
