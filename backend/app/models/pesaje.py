from datetime import datetime, timezone
from app import db


class Pesaje(db.Model):
    """Modelo para almacenar los pesajes realizados"""
    
    __tablename__ = 'pesajes'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Datos del pesaje
    peso_kg = db.Column(db.Float, nullable=False)
    fecha_hora = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Datos de la Orden de Producción (del QR escaneado)
    molde = db.Column(db.String(100), nullable=True)  # MOL: CERNIDOR ROMANO
    maquina = db.Column(db.String(50), nullable=True)  # MÁQ: HT-250B
    nro_op = db.Column(db.String(20), nullable=True)  # NºOP: OP1354
    turno = db.Column(db.String(20), nullable=True)  # TUR: Diurno/Nocturno
    fecha_orden_trabajo = db.Column(db.Date, nullable=True)  # F.OT: 2026-01-03
    nro_orden_trabajo = db.Column(db.String(20), nullable=True)  # NºOT: 0000
    
    # Datos adicionales
    operador = db.Column(db.String(100), nullable=True)  # OPE: Admin
    color = db.Column(db.String(50), nullable=True)  # COL:
    
    # Pieza/componente seleccionado (del dropdown)
    pieza_sku = db.Column(db.String(50), nullable=True)
    pieza_nombre = db.Column(db.String(100), nullable=True)
    
    observaciones = db.Column(db.Text, nullable=True)
    
    # Estado del sticker
    sticker_impreso = db.Column(db.Boolean, default=False)
    fecha_impresion = db.Column(db.DateTime, nullable=True)
    
    # Sincronización con API central
    sincronizado = db.Column(db.Boolean, default=False)
    fecha_sincronizacion = db.Column(db.DateTime, nullable=True)
    
    # QR original escaneado
    qr_data_original = db.Column(db.String(500), nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'peso_kg': self.peso_kg,
            'fecha_hora': self.fecha_hora.isoformat() if self.fecha_hora else None,
            'molde': self.molde,
            'maquina': self.maquina,
            'nro_op': self.nro_op,
            'turno': self.turno,
            'fecha_orden_trabajo': self.fecha_orden_trabajo.isoformat() if self.fecha_orden_trabajo else None,
            'nro_orden_trabajo': self.nro_orden_trabajo,
            'operador': self.operador,
            'color': self.color,
            'pieza_sku': self.pieza_sku,
            'pieza_nombre': self.pieza_nombre,
            'observaciones': self.observaciones,
            'sticker_impreso': self.sticker_impreso,
            'fecha_impresion': self.fecha_impresion.isoformat() if self.fecha_impresion else None,
            'sincronizado': self.sincronizado,
            'fecha_sincronizacion': self.fecha_sincronizacion.isoformat() if self.fecha_sincronizacion else None,
            'qr_data_original': self.qr_data_original,
        }
    
    @staticmethod
    def parse_qr_data(qr_string: str) -> dict:
        """
        Parsea el string del QR escaneado.
        
        Soporta dos formatos:
        1. URL de Google Forms: "https://docs.google.com/forms/...?entry.374896580=OP-1354&entry.1779940712=MOLDE"
        2. Formato legacy: "398;CERNIDOR ROMANO;HT-250B;OP1354;DIURNO;2026-01-03;0000"
        """
        from urllib.parse import urlparse, parse_qs, unquote_plus
        
        # Limpiar: algunos scanners duplican el contenido o agregan saltos
        qr_string = qr_string.strip()
        
        # Si hay URL duplicada, quedarse con la primera
        if 'viewform' in qr_string:
            idx = qr_string.find('viewform')
            idx2 = qr_string.find('viewform', idx + 8)
            if idx2 > 0:
                # Cortar en el punto donde empieza la URL duplicada
                # Buscar el inicio de la segunda URL (https)
                cut_point = qr_string.find('https', idx + 1)
                if cut_point > 0:
                    qr_string = qr_string[:cut_point]
        
        # Intentar parsear como URL de Google Forms
        if 'docs.google.com/forms' in qr_string or 'entry.' in qr_string:
            try:
                parsed = urlparse(qr_string)
                params = parse_qs(parsed.query)
                
                # Extraer valores de los entry fields
                # Mapeo de entry IDs a nombres de campo
                entry_map = {
                    'entry.374896580': 'nro_op',      # numero_op
                    'entry.1779940712': 'molde',       # molde
                    'entry.885430358': 'peso_unitario', # peso_unitario
                    'entry.873760233': 'maquina',      # maquina
                }
                
                result = {}
                for entry_id, field_name in entry_map.items():
                    if entry_id in params:
                        # parse_qs retorna listas, tomar primer valor
                        value = params[entry_id][0] if params[entry_id] else ''
                        result[field_name] = unquote_plus(value)
                
                # Si encontramos al menos nro_op, es válido
                if result.get('nro_op'):
                    return result
                    
            except Exception as e:
                print(f"Error parsing Google Forms URL: {e}")
        
        # Fallback: formato legacy con punto y coma
        parts = qr_string.split(';')
        if len(parts) >= 7:
            return {
                'id_registro': parts[0].strip(),
                'molde': parts[1].strip(),
                'maquina': parts[2].strip(),
                'nro_op': parts[3].strip(),
                'turno': parts[4].strip(),
                'fecha_orden_trabajo': parts[5].strip(),
                'nro_orden_trabajo': parts[6].strip() if len(parts) > 6 else None,
            }
        
        return {}
    
    def generate_sticker_qr_data(self) -> str:
        """
        Genera el string para el QR del sticker.
        Incluye toda la información del pesaje.
        """
        fecha_hora_str = self.fecha_hora.strftime('%Y-%m-%d/%H:%M:%S') if self.fecha_hora else ''
        fecha_ot_str = self.fecha_orden_trabajo.strftime('%Y-%m-%d') if self.fecha_orden_trabajo else ''
        
        return ';'.join([
            self.molde or '',
            self.maquina or '',
            self.nro_op or '',
            self.turno or '',
            fecha_ot_str,
            self.nro_orden_trabajo or '',
            self.operador or '',
            self.color or '',
            fecha_hora_str,
            f'{self.peso_kg:.1f}'
        ])
    
    def __repr__(self):
        return f'<Pesaje {self.id}: {self.peso_kg}kg - {self.molde}>'
