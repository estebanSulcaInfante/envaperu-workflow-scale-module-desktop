from datetime import datetime
from app import db


class MoldePiezasCache(db.Model):
    """Cache local de moldes y piezas para operación offline"""
    
    __tablename__ = 'molde_piezas_cache'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Datos del molde
    molde_codigo = db.Column(db.String(50), index=True)
    molde_nombre = db.Column(db.String(100), index=True)
    peso_tiro_gr = db.Column(db.Float)
    tiempo_ciclo_std = db.Column(db.Float)
    
    # Datos de la pieza
    pieza_sku = db.Column(db.String(50))
    pieza_nombre = db.Column(db.String(100))
    tipo = db.Column(db.String(20))  # KIT, COMPONENTE, SIMPLE
    cavidades = db.Column(db.Integer)
    peso_unitario_gr = db.Column(db.Float)
    
    # Control de sincronización
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Índice único para evitar duplicados
    __table_args__ = (
        db.UniqueConstraint('molde_codigo', 'pieza_sku', name='uq_molde_pieza_cache'),
    )
    
    def to_dict(self):
        return {
            'molde_codigo': self.molde_codigo,
            'molde_nombre': self.molde_nombre,
            'pieza_sku': self.pieza_sku,
            'pieza_nombre': self.pieza_nombre,
            'tipo': self.tipo,
            'cavidades': self.cavidades,
            'peso_unitario_gr': self.peso_unitario_gr
        }
