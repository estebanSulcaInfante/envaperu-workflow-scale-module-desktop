"""
Tests para el modelo CorrelativoCache y endpoint de anulación.
"""
import pytest
from app import create_app, db
from app.models.correlativo_cache import (
    CorrelativoCache, 
    consumir_local, 
    agregar_a_cache, 
    get_disponibles_count,
    get_siguiente_local
)


@pytest.fixture
def app():
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


class TestCorrelativoCacheModel:
    """Tests del modelo CorrelativoCache"""
    
    def test_agregar_correlativos(self, app):
        """Agregar correlativos al cache"""
        with app.app_context():
            count = agregar_a_cache([30001, 30002, 30003])
            assert count == 3
            assert get_disponibles_count() == 3
    
    def test_consumir_correlativo(self, app):
        """Consumir correlativo marca como usado"""
        with app.app_context():
            agregar_a_cache([30001, 30002])
            
            corr = consumir_local(nro_op='OP-1322', molde='BALDE')
            
            assert corr == 30001
            assert get_disponibles_count() == 1
            
            # Verificar que se guardó la info
            usado = db.session.get(CorrelativoCache, 30001)
            assert usado.usado == True
            assert usado.nro_op == 'OP-1322'
            assert usado.molde == 'BALDE'
    
    def test_anular_correlativo(self, app):
        """Anular correlativo guarda motivo y fecha"""
        with app.app_context():
            agregar_a_cache([30001])
            
            corr = db.session.get(CorrelativoCache, 30001)
            corr.anular("Hoja destruida por agua")
            db.session.commit()
            
            # Verificar
            anulado = db.session.get(CorrelativoCache, 30001)
            assert anulado.usado == True
            assert anulado.anulado == True
            assert anulado.motivo_anulacion == "Hoja destruida por agua"
            assert anulado.fecha_anulacion is not None
    
    def test_siguiente_salta_anulados(self, app):
        """get_siguiente_local salta correlativos anulados"""
        with app.app_context():
            agregar_a_cache([30001, 30002, 30003])
            
            # Anular el primero
            corr = db.session.get(CorrelativoCache, 30001)
            corr.anular("Test")
            db.session.commit()
            
            # El siguiente debe ser 30002
            sig = get_siguiente_local()
            assert sig.correlativo == 30002


class TestAnularAPI:
    """Tests del endpoint /cache/anular"""
    
    def test_anular_siguiente(self, client, app):
        """Anular el siguiente correlativo disponible"""
        with app.app_context():
            agregar_a_cache([30001, 30002])
        
        response = client.post('/api/rdp/cache/anular', json={
            'motivo': 'Hoja mojada'
        })
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] == True
        assert data['correlativo'] == 30001
        assert data['motivo'] == 'Hoja mojada'
        assert 'fecha' in data
    
    def test_anular_especifico(self, client, app):
        """Anular correlativo específico"""
        with app.app_context():
            agregar_a_cache([30001, 30002, 30003])
        
        response = client.post('/api/rdp/cache/anular', json={
            'correlativo': 30002,
            'motivo': 'Roto accidentalmente'
        })
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['correlativo'] == 30002
    
    def test_anular_sin_disponibles(self, client):
        """Error si no hay correlativos disponibles"""
        response = client.post('/api/rdp/cache/anular', json={
            'motivo': 'Test'
        })
        
        assert response.status_code == 404
    
    def test_listar_anulados(self, client, app):
        """Listar todos los correlativos anulados"""
        with app.app_context():
            agregar_a_cache([30001, 30002, 30003])
            c1 = db.session.get(CorrelativoCache, 30001)
            c1.anular("Motivo 1")
            c2 = db.session.get(CorrelativoCache, 30002)
            c2.anular("Motivo 2")
            db.session.commit()
        
        response = client.get('/api/rdp/cache/anulados')
        
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 2
        assert all(c['anulado'] for c in data)
