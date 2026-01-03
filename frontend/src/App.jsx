import { useState, useEffect } from 'react';
import { pesajesApi, balanzaApi } from './services/api';

function App() {
  // Connection state
  const [connected, setConnected] = useState(false);
  const [listening, setListening] = useState(false);
  
  // Weight state
  const [peso, setPeso] = useState(0);
  
  // QR and form data
  const [qrInput, setQrInput] = useState('');
  const [formData, setFormData] = useState({
    molde: '',
    maquina: '',
    nro_op: '',
    turno: '',
    fecha_orden_trabajo: '',
    nro_orden_trabajo: '',
    operador: '',
    color: ''
  });
  
  // Pesajes list
  const [pesajes, setPesajes] = useState([]);
  
  // UI state
  const [toast, setToast] = useState(null);
  const [stickerPreview, setStickerPreview] = useState(null);

  // Load status and pesajes on mount
  useEffect(() => {
    checkStatus();
    loadPesajes();
  }, []);

  // Poll for weight when listening
  useEffect(() => {
    let interval;
    if (listening) {
      interval = setInterval(async () => {
        try {
          const { data } = await balanzaApi.ultimoPeso();
          if (data.peso_kg !== null) {
            setPeso(data.peso_kg);
          }
        } catch (err) {
          console.error('Error polling peso:', err);
        }
      }, 500);
    }
    return () => clearInterval(interval);
  }, [listening]);

  const checkStatus = async () => {
    try {
      const { data } = await balanzaApi.status();
      setConnected(data.connected);
      setListening(data.listening);
    } catch (err) {
      console.error('Error checking status:', err);
    }
  };

  const loadPesajes = async () => {
    try {
      const { data } = await pesajesApi.listar(1, 15);
      setPesajes(data.items || []);
    } catch (err) {
      console.error('Error loading pesajes:', err);
    }
  };

  const showToast = (message, type = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // Parse QR input
  const handleQrInput = async (value) => {
    setQrInput(value);
    
    // Try to parse when it looks like a complete QR
    if (value.includes(';') && value.split(';').length >= 6) {
      try {
        const { data } = await pesajesApi.parseQr(value);
        if (data.status === 'ok') {
          setFormData(prev => ({
            ...prev,
            molde: data.data.molde || '',
            maquina: data.data.maquina || '',
            nro_op: data.data.nro_op || '',
            turno: data.data.turno || '',
            fecha_orden_trabajo: data.data.fecha_orden_trabajo || '',
            nro_orden_trabajo: data.data.nro_orden_trabajo || ''
          }));
          showToast('QR procesado correctamente');
        }
      } catch (err) {
        console.error('Error parsing QR:', err);
      }
    }
  };

  const handleConnect = async () => {
    try {
      if (connected) {
        await balanzaApi.desconectar();
        setConnected(false);
        setListening(false);
      } else {
        const { data } = await balanzaApi.conectar();
        setConnected(data.connected);
        if (data.connected) {
          await balanzaApi.iniciarEscucha();
          setListening(true);
        }
      }
    } catch (err) {
      showToast('Error de conexión', 'error');
    }
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleGrabar = async () => {
    if (peso <= 0) {
      showToast('El peso debe ser mayor a 0', 'error');
      return;
    }

    try {
      const { data } = await pesajesApi.crear({
        peso_kg: peso,
        ...formData,
        qr_data_original: qrInput
      });
      showToast('Pesaje guardado correctamente');
      loadPesajes();
      
      // Show sticker preview
      const preview = await pesajesApi.previewSticker(data.id);
      setStickerPreview(preview.data.preview);
      
    } catch (err) {
      showToast('Error al guardar', 'error');
    }
  };

  const handleImprimir = async (id) => {
    try {
      await pesajesApi.imprimir(id);
      showToast('Sticker enviado a impresión');
      loadPesajes();
    } catch (err) {
      showToast('Error al imprimir', 'error');
    }
  };

  const handleReimprimir = async () => {
    if (pesajes.length > 0) {
      handleImprimir(pesajes[0].id);
    }
  };

  const handleLimpiar = () => {
    setQrInput('');
    setFormData({
      molde: '',
      maquina: '',
      nro_op: '',
      turno: '',
      fecha_orden_trabajo: '',
      nro_orden_trabajo: '',
      operador: '',
      color: ''
    });
    setStickerPreview(null);
  };

  const formatDate = (isoDate) => {
    if (!isoDate) return '';
    const date = new Date(isoDate);
    return date.toLocaleString('es-PE', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <h1>⚖️ Sistema de Pesado - ENVAPERU</h1>
        <div className="header-right">
          <div 
            className={`connection-badge ${connected ? 'connected' : 'disconnected'}`}
            onClick={handleConnect}
            style={{ cursor: 'pointer' }}
          >
            <span className="status-dot"></span>
            {connected ? 'Balanza Conectada' : 'Balanza Desconectada'}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="main-content">
        {/* Left Panel - Form */}
        <div className="panel">
          <div className="panel-header">📋 ASIGNACIÓN DE TAREAS</div>
          <div className="panel-body">
            
            {/* QR Input */}
            <div className="qr-section">
              <div className="qr-input-group">
                <label>Código QR</label>
                <input
                  type="text"
                  value={qrInput}
                  onChange={(e) => handleQrInput(e.target.value)}
                  placeholder="Escanear QR de Registro Diario..."
                  autoFocus
                />
              </div>
            </div>

            {/* Form Fields */}
            <div className="form-grid">
              <div className="form-group">
                <label>Molde</label>
                <input
                  type="text"
                  name="molde"
                  value={formData.molde}
                  onChange={handleInputChange}
                  disabled
                />
              </div>
              <div className="form-group">
                <label>Nro Orden de Trabajo</label>
                <input
                  type="text"
                  name="nro_orden_trabajo"
                  value={formData.nro_orden_trabajo}
                  onChange={handleInputChange}
                  className="highlight"
                />
              </div>
              <div className="form-group">
                <label>Máquina</label>
                <input
                  type="text"
                  name="maquina"
                  value={formData.maquina}
                  onChange={handleInputChange}
                  disabled
                />
              </div>
              <div className="form-group">
                <label>Fecha Orden de Trabajo</label>
                <input
                  type="date"
                  name="fecha_orden_trabajo"
                  value={formData.fecha_orden_trabajo}
                  onChange={handleInputChange}
                />
              </div>
              <div className="form-group">
                <label>Nro OP</label>
                <input
                  type="text"
                  name="nro_op"
                  value={formData.nro_op}
                  onChange={handleInputChange}
                  disabled
                />
              </div>
              <div className="form-group">
                <label>Operador</label>
                <input
                  type="text"
                  name="operador"
                  value={formData.operador}
                  onChange={handleInputChange}
                  placeholder="Nombre del operador"
                />
              </div>
              <div className="form-group">
                <label>Turno</label>
                <select
                  name="turno"
                  value={formData.turno}
                  onChange={handleInputChange}
                >
                  <option value="">Seleccionar...</option>
                  <option value="DIURNO">DIURNO</option>
                  <option value="NOCTURNO">NOCTURNO</option>
                </select>
              </div>
              <div className="form-group">
                <label>Color</label>
                <input
                  type="text"
                  name="color"
                  value={formData.color}
                  onChange={handleInputChange}
                  placeholder="Color del producto"
                />
              </div>
            </div>

            {/* Weight Display */}
            <div className="weight-display-container">
              <div className="weight-display">
                <span className="weight-value">{peso.toFixed(1)}</span>
                <span className="weight-unit">kg</span>
                <div className="weight-status">
                  {listening ? '📡 Escuchando balanza...' : 'Conectar balanza para capturar peso'}
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="actions-row">
              <button className="btn btn-warning" onClick={handleReimprimir}>
                🖨️ Re-imprimir etiqueta
              </button>
              <button className="btn btn-success" onClick={handleGrabar} disabled={peso <= 0}>
                💾 Grabar
              </button>
              <button className="btn btn-secondary" onClick={handleLimpiar}>
                🗑️ Limpiar
              </button>
            </div>

            {/* Sticker Preview */}
            {stickerPreview && (
              <div className="sticker-preview">
                {stickerPreview}
                <div className="qr-placeholder">[QR CODE]</div>
              </div>
            )}
          </div>
        </div>

        {/* Right Panel - Recent Pesajes */}
        <div className="panel">
          <div className="panel-header">📋 Pesajes Recientes</div>
          <div className="panel-body">
            <div className="pesajes-list">
              {pesajes.length === 0 && (
                <p style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '2rem' }}>
                  No hay pesajes registrados
                </p>
              )}
              {pesajes.map((p) => (
                <div key={p.id} className="pesaje-item">
                  <div className="pesaje-info">
                    <span className="peso">{p.peso_kg.toFixed(1)} kg</span>
                    <span className="meta">
                      {p.molde || 'Sin molde'} • {p.nro_op || ''} • {formatDate(p.fecha_hora)}
                    </span>
                  </div>
                  <div className="pesaje-actions">
                    <button 
                      className="btn btn-icon btn-secondary"
                      onClick={() => handleImprimir(p.id)}
                      title="Imprimir sticker"
                    >
                      🖨️
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>

      {/* Toast */}
      {toast && (
        <div className={`toast ${toast.type}`}>
          {toast.message}
        </div>
      )}
    </div>
  );
}

export default App;
