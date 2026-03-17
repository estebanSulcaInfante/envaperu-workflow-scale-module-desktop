import sqlite3
import os

def migrate_timestamps():
    # La base de datos de Flask con SQLAlchemy suele estar en la carpeta instance/
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'instance', 'app.db')
    
    # Fallback si por alguna razon esta en la raiz
    if not os.path.exists(db_path):
        db_path = os.path.join(base_dir, 'app.db')
        
    if not os.path.exists(db_path):
        print(f"❌ Error: No se encontró el archivo de base de datos SQLite en: {db_path}")
        print("Asegúrate de ejecutar este script dentro de la carpeta 'backend'.")
        return

    print(f"📦 Conectando a la BD: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Consultas SQL nativas de SQLite para restar 5 horas a las fechas
    consultas = [
        # Tabla: PESAJE
        "UPDATE pesajes SET fecha_hora = datetime(fecha_hora, '-5 hours') WHERE fecha_hora IS NOT NULL;",
        "UPDATE pesajes SET fecha_impresion = datetime(fecha_impresion, '-5 hours') WHERE fecha_impresion IS NOT NULL;",
        "UPDATE pesajes SET fecha_sincronizacion = datetime(fecha_sincronizacion, '-5 hours') WHERE fecha_sincronizacion IS NOT NULL;",
        "UPDATE pesajes SET deleted_at = datetime(deleted_at, '-5 hours') WHERE deleted_at IS NOT NULL;",
        
        # Tabla: OPS_CERRADAS
        "UPDATE ops_cerradas SET fecha_cierre = datetime(fecha_cierre, '-5 hours') WHERE fecha_cierre IS NOT NULL;"
    ]

    print("⏳ Ejecutando conversión de zonas horarias (UTC -> UTC-5)...")
    
    try:
        total_afectadas = 0
        for sql in consultas:
            cursor.execute(sql)
            afectadas = cursor.rowcount
            total_afectadas += afectadas
            print(f"  ✓ {sql.split('SET')[1].split('=')[0].strip().ljust(22)} -> {afectadas} filas ajustadas.")
            
        conn.commit()
        print(f"✅ ¡Éxito! Migración completada. Un total de {total_afectadas} celdas de fecha/hora fueron convertidas a hora de Perú.")
        
    except sqlite3.Error as e:
        conn.rollback()
        print(f"❌ Error durante la ejecución SQL: {e}")
        
    finally:
        conn.close()

if __name__ == '__main__':
    migrate_timestamps()
