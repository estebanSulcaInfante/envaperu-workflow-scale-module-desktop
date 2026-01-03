import axios from 'axios';

const API_BASE = '/api';

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

export default api;
