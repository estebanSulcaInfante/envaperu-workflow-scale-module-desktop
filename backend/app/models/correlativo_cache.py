"""
Cache local de correlativos para funcionamiento offline.
"""
from datetime import datetime, timezone
from app import db


class CorrelativoCache(db.Model):
    """
    Cache local de correlativos reservados del servidor central.
    Permite generar RDPs sin conexión.
    """
    __tablename__ = 'correlativo_cache'
    
    correlativo = db.Column(db.Integer, primary_key=True)  # El número del correlativo
    fecha_reserva = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    usado = db.Column(db.Boolean, default=False)
    fecha_uso = db.Column(db.DateTime, nullable=True)
    
    # Datos del RDP generado (para reconciliación)
    nro_op = db.Column(db.String(50), nullable=True)
    molde = db.Column(db.String(100), nullable=True)
    
    # Campos de anulación
    anulado = db.Column(db.Boolean, default=False)
    fecha_anulacion = db.Column(db.DateTime, nullable=True)
    motivo_anulacion = db.Column(db.String(200), nullable=True)
    
    def marcar_usado(self, nro_op=None, molde=None):
        """Marca el correlativo como usado."""
        self.usado = True
        self.fecha_uso = datetime.now(timezone.utc)
        self.nro_op = nro_op
        self.molde = molde
    
    def anular(self, motivo: str):
        """Anula el correlativo (hoja destruida/perdida)."""
        self.usado = True
        self.anulado = True
        self.fecha_anulacion = datetime.now(timezone.utc)
        self.motivo_anulacion = motivo
    
    def to_dict(self):
        return {
            'correlativo': self.correlativo,
            'fecha_reserva': self.fecha_reserva.isoformat() if self.fecha_reserva else None,
            'usado': self.usado,
            'fecha_uso': self.fecha_uso.isoformat() if self.fecha_uso else None,
            'nro_op': self.nro_op,
            'molde': self.molde,
            'anulado': self.anulado,
            'fecha_anulacion': self.fecha_anulacion.isoformat() if self.fecha_anulacion else None,
            'motivo_anulacion': self.motivo_anulacion
        }
    
    def __repr__(self):
        status = "✗" if self.anulado else ("✓" if self.usado else "○")
        return f'<CorrelativoCache {self.correlativo} {status}>'


# === Funciones de gestión de cache ===

CACHE_THRESHOLD = 50  # Reponer cuando quedan <= 50
CACHE_BATCH_SIZE = 100  # Cuántos pedir al reponer


def get_disponibles_count():
    """Cuenta correlativos disponibles en cache local."""
    return CorrelativoCache.query.filter_by(usado=False).count()


def get_siguiente_local():
    """
    Obtiene el siguiente correlativo disponible del cache local.
    Retorna None si no hay.
    """
    siguiente = CorrelativoCache.query.filter_by(usado=False).order_by(
        CorrelativoCache.correlativo
    ).first()
    return siguiente


def consumir_local(nro_op=None, molde=None):
    """
    Consume el siguiente correlativo del cache local.
    Retorna el número de correlativo o None si no hay disponibles.
    """
    siguiente = get_siguiente_local()
    if siguiente is None:
        return None
    
    siguiente.marcar_usado(nro_op=nro_op, molde=molde)
    db.session.commit()
    
    return siguiente.correlativo


def agregar_a_cache(correlativos: list):
    """
    Agrega una lista de correlativos al cache local.
    Ignora duplicados.
    """
    count = 0
    for corr in correlativos:
        existente = db.session.get(CorrelativoCache, corr)
        if not existente:
            nuevo = CorrelativoCache(correlativo=corr)
            db.session.add(nuevo)
            count += 1
    
    db.session.commit()
    return count


def necesita_reponer():
    """Verifica si se necesita reponer el cache."""
    return get_disponibles_count() <= CACHE_THRESHOLD
