"""
Servicio de sincronización con el Backend Central.
Envía pesajes pendientes cuando hay conectividad.
"""
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from flask import current_app

from app import db
from app.models.pesaje import Pesaje


class SyncService:
    """Servicio para sincronizar pesajes con el backend central."""
    
    def __init__(self, central_api_url: str = None):
        """
        Inicializa el servicio de sync.
        
        Args:
            central_api_url: URL base del API central (ej: http://192.168.1.100:5000/api)
        """
        self.central_api_url = central_api_url
        self._connected = False
    
    def _get_api_url(self) -> str:
        """Obtiene la URL del API central desde config o instancia."""
        if self.central_api_url:
            return self.central_api_url
        return current_app.config.get('CENTRAL_API_URL', 'http://localhost:5000/api')
    
    def check_connectivity(self) -> bool:
        """
        Verifica si hay conectividad con el backend central.
        
        Returns:
            True si hay conexión, False si no.
        """
        try:
            url = f"{self._get_api_url()}/ordenes"
            response = requests.get(url, timeout=5)
            self._connected = response.status_code == 200
            return self._connected
        except Exception:
            self._connected = False
            return False
    
    def get_pending_pesajes(self) -> List[Pesaje]:
        """
        Obtiene todos los pesajes pendientes de sincronización.
        
        Returns:
            Lista de Pesajes con sincronizado=False
        """
        return Pesaje.query.filter_by(sincronizado=False).all()
    
    def _pesaje_to_sync_payload(self, pesaje: Pesaje) -> Dict[str, Any]:
        """
        Convierte un Pesaje al formato esperado por el endpoint de sync.
        """
        return {
            'local_id': pesaje.id,
            'peso_kg': pesaje.peso_kg,
            'fecha_hora': pesaje.fecha_hora.isoformat() if pesaje.fecha_hora else None,
            'nro_op': pesaje.nro_op,
            'turno': pesaje.turno,
            'fecha_ot': pesaje.fecha_orden_trabajo.isoformat() if pesaje.fecha_orden_trabajo else None,
            'nro_ot': pesaje.nro_orden_trabajo,
            'maquina': pesaje.maquina,
            'molde': pesaje.molde,
            'color': pesaje.color,
            'operador': pesaje.operador,
            'qr_data': pesaje.qr_data_original
        }
    
    def sync_pesajes(self, pesajes: List[Pesaje] = None) -> Dict[str, Any]:
        """
        Sincroniza pesajes con el backend central.
        
        Args:
            pesajes: Lista de pesajes a sincronizar. Si es None, usa los pendientes.
        
        Returns:
            Resultado de la sincronización con synced, errors, etc.
        """
        if pesajes is None:
            pesajes = self.get_pending_pesajes()
        
        if not pesajes:
            return {
                'success': True,
                'message': 'No hay pesajes pendientes',
                'synced': [],
                'errors': []
            }
        
        # Verificar conectividad
        if not self.check_connectivity():
            return {
                'success': False,
                'message': 'Sin conexión con el backend central',
                'synced': [],
                'errors': [{'error': 'No connectivity'}]
            }
        
        # Preparar payload
        payload = {
            'pesajes': [self._pesaje_to_sync_payload(p) for p in pesajes]
        }
        
        try:
            url = f"{self._get_api_url()}/sync/pesajes"
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code in [200, 207]:
                result = response.json()
                
                # Marcar como sincronizados los exitosos
                synced_ids = [s['local_id'] for s in result.get('synced', [])]
                for pesaje in pesajes:
                    if pesaje.id in synced_ids:
                        pesaje.sincronizado = True
                        pesaje.fecha_sincronizacion = datetime.now(timezone.utc)
                
                db.session.commit()
                
                return {
                    'success': result.get('success', False),
                    'message': f'Sincronizados {len(synced_ids)} pesajes',
                    'synced': result.get('synced', []),
                    'errors': result.get('errors', [])
                }
            else:
                return {
                    'success': False,
                    'message': f'Error HTTP {response.status_code}',
                    'synced': [],
                    'errors': [{'error': response.text}]
                }
                
        except requests.exceptions.Timeout:
            return {
                'success': False,
                'message': 'Timeout al conectar con el backend central',
                'synced': [],
                'errors': [{'error': 'Timeout'}]
            }
        except Exception as e:
            return {
                'success': False,
                'message': str(e),
                'synced': [],
                'errors': [{'error': str(e)}]
            }
    
    def get_status(self) -> Dict[str, Any]:
        """
        Retorna el estado actual de la sincronización.
        """
        pending_count = Pesaje.query.filter_by(sincronizado=False).count()
        synced_count = Pesaje.query.filter_by(sincronizado=True).count()
        
        return {
            'connected': self._connected,
            'central_api_url': self._get_api_url(),
            'pending_count': pending_count,
            'synced_count': synced_count,
            'last_check': datetime.now(timezone.utc).isoformat()
        }


# Instancia global
_sync_service: Optional[SyncService] = None


def get_sync_service() -> SyncService:
    """Obtiene la instancia del servicio de sync."""
    global _sync_service
    if _sync_service is None:
        _sync_service = SyncService()
    return _sync_service
