import axios from 'axios';

// Usar URL absoluta para evitar problemas de proxy
const API_BASE = 'http://127.0.0.1:5050/api';

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json'
  }
});

// ===== Pesajes =====
export const pesajesApi = {
  listar: (page = 1, perPage = 20) => 
    api.get(`/pesajes?page=${page}&per_page=${perPage}`),
  
  crear: (data) => 
    api.post('/pesajes', data),
  
  obtener: (id) => 
    api.get(`/pesajes/${id}`),
  
  actualizar: (id, data) => 
    api.put(`/pesajes/${id}`, data),
  
  eliminar: (id) => 
    api.delete(`/pesajes/${id}`),
  
  imprimir: (id) => 
    api.post(`/pesajes/${id}/imprimir`),
  
  previewSticker: (id) =>
    api.get(`/pesajes/${id}/preview-sticker`),
  
  parseQr: (qrData) =>
    api.post('/pesajes/parse-qr', { qr_data: qrData }),
  
  sinSincronizar: () => 
    api.get('/pesajes/sin-sincronizar'),
  
  marcarSincronizado: (ids) => 
    api.post('/pesajes/marcar-sincronizado', { ids })
};

// ===== Balanza =====
export const balanzaApi = {
  status: () => 
    api.get('/balanza/status'),
  
  conectar: () => 
    api.post('/balanza/conectar'),
  
  desconectar: () => 
    api.post('/balanza/desconectar'),
  
  iniciarEscucha: () => 
    api.post('/balanza/iniciar-escucha'),
  
  detenerEscucha: () => 
    api.post('/balanza/detener-escucha'),
  
  ultimoPeso: () => 
    api.get('/balanza/ultimo-peso'),
  
  pesosPendientes: () => 
    api.get('/balanza/pesos-pendientes')
};

// ===== Sync (catálogo moldes) =====
export const syncApi = {
  syncMoldes: () =>
    api.post('/sync/moldes'),
  
  getCachedPiezas: (moldeNombre) =>
    api.get(`/sync/cache/piezas/${encodeURIComponent(moldeNombre)}`),
  
  status: () =>
    api.get('/sync/status')
};

// ===== RDP (Registro Diario Producción) =====
export const rdpApi = {
  getSiguiente: () =>
    api.get('/rdp/siguiente'),
  
  generar: (data) =>
    api.post('/rdp/generar', data),
  
  anular: (correlativo, motivo) =>
    api.post('/rdp/cache/anular', { correlativo, motivo }),
  
  cacheStatus: () =>
    api.get('/rdp/cache/status'),
  
  cacheReponer: () =>
    api.post('/rdp/cache/reponer')
};

export default api;
