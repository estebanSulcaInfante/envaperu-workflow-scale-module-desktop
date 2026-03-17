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
  
  buscar: (filters = {}) => {
    const params = new URLSearchParams();
    if (filters.id) params.append('id', filters.id);
    if (filters.nro_op) params.append('nro_op', filters.nro_op);
    if (filters.molde) params.append('molde', filters.molde);
    if (filters.nro_ot) params.append('nro_ot', filters.nro_ot);
    if (filters.fecha_inicio) params.append('fecha_inicio', filters.fecha_inicio);
    if (filters.fecha_fin) params.append('fecha_fin', filters.fecha_fin);
    if (filters.page) params.append('page', filters.page);
    if (filters.per_page) params.append('per_page', filters.per_page);
    return api.get(`/pesajes/buscar?${params.toString()}`);
  },

  crear: (data) => 
    api.post('/pesajes', data),
  
  obtener: (id) => 
    api.get(`/pesajes/${id}`),
  
  actualizar: (id, data) => 
    api.put(`/pesajes/${id}`, data),
  
  eliminar: (id) => 
    api.delete(`/pesajes/${id}`),
  
  eliminarBulk: (ids) =>
    api.post('/pesajes/bulk-delete', { ids }),
  
  imprimir: (id) => 
    api.post(`/pesajes/${id}/imprimir`),
  
  previewSticker: (id) =>
    api.get(`/pesajes/${id}/preview-sticker`),
  
  parseQr: (qrData) =>
    api.post('/pesajes/parse-qr', { qr_data: qrData }),
  
  sinSincronizar: () => 
    api.get('/pesajes/sin-sincronizar'),
  
  marcarSincronizado: (ids) => 
    api.post('/pesajes/marcar-sincronizado', { ids }),
    
  exportarExcel: (fechaInicio, fechaFin) => {
    let url = '/pesajes/exportar';
    const params = new URLSearchParams();
    if (fechaInicio) params.append('fecha_inicio', fechaInicio);
    if (fechaFin) params.append('fecha_fin', fechaFin);
    
    const qs = params.toString();
    if (qs) url += `?${qs}`;
    
    return api.get(url, { responseType: 'blob' });
  }
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
    api.post('/rdp/cache/reponer'),
  
  reimprimir: (correlativo) =>
    api.post('/rdp/reimprimir', { correlativo })
};

// ===== Avance Local =====
export const avanceApi = {
  resumen: () =>
    api.get('/avance/resumen')
};

// ===== OPs (Cerrar/Reabrir) =====
export const opsApi = {
  activas: () =>
    api.get('/ops/activas'),
  
  cerradas: () =>
    api.get('/ops/cerradas'),
  
  cerrar: (data) =>
    api.post('/ops/cerrar', data),
  
  reabrir: (data) =>
    api.post('/ops/reabrir', data)
};

export default api;

