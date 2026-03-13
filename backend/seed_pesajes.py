from app import create_app, db
from app.models.pesaje import Pesaje
from datetime import datetime, timedelta
import random

def seed_db():
    app = create_app()
    with app.app_context():
        print("Creando 50 pesajes falsos...")
        
        ops = ['OP1001', 'OP1002', 'OP1003', 'OP1004', 'OP1005']
        moldes = ['CERNIDOR', 'TAZA', 'VASO', 'PLATO', 'JARRA']
        colores = ['ROJO', 'AZUL', 'VERDE', 'SIN COLOR', 'NEGRO']
        operadores = ['Juan', 'Pedro', 'Maria', 'Ana', 'Luis']
        
        now = datetime.now()
        
        for i in range(50):
            op = random.choice(ops)
            pesaje = Pesaje(
                nro_op=op,
                molde=random.choice(moldes),
                nro_orden_trabajo=f"OT{random.randint(1000, 9999)}",
                color=random.choice(colores),
                maquina=f"MAQ-{random.randint(1, 10)}",
                turno=random.choice(['DIA', 'NOCHE']),
                operador=random.choice(operadores),
                peso_kg=round(random.uniform(5.0, 25.0), 2),
                fecha_hora=now - timedelta(days=random.randint(0, 60), hours=random.randint(0, 23), minutes=random.randint(0, 59))
            )
            db.session.add(pesaje)
            
        db.session.commit()
        print("¡Pesajes creados con éxito!")

if __name__ == '__main__':
    seed_db()
