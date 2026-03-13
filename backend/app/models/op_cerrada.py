from datetime import datetime, timezone
from app import db


class OpCerrada(db.Model):
    """Registro local de OPs cerradas (standalone, sin API central)."""
    
    __tablename__ = 'ops_cerradas'
    
    id = db.Column(db.Integer, primary_key=True)
    nro_op = db.Column(db.String(20), nullable=False, unique=True)
    molde = db.Column(db.String(100), nullable=True)
    motivo = db.Column(db.String(200), nullable=True)
    fecha_cierre = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'nro_op': self.nro_op,
            'molde': self.molde,
            'motivo': self.motivo,
            'fecha_cierre': self.fecha_cierre.isoformat() if self.fecha_cierre else None,
        }
    
    def __repr__(self):
        return f'<OpCerrada {self.nro_op}>'
