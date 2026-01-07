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
    
    // Auto-llenar fecha con fecha actual
    const today = new Date().toISOString().split('T')[0];
    setFormData(prev => ({
      ...prev,
      fecha_orden_trabajo: today
    }));
  }, []);

  // Poll for weight when listening - AUTO GRABAR cuando llega peso nuevo
  useEffect(() => {
    let interval;
    if (listening) {
      interval = setInterval(async () => {
        try {
          const { data } = await balanzaApi.ultimoPeso();
          // Si hay peso nuevo y válido (>= 1kg), auto-grabar e imprimir
          if (data.peso_kg !== null && data.peso_kg !== peso) {
            const nuevoPeso = data.peso_kg;
            console.log(`[AUTO] Peso recibido: ${nuevoPeso} kg, nro_op: ${formData.nro_op || '(vacío)'}`);
            setPeso(nuevoPeso);
            
            // Auto-grabar e imprimir si el peso es válido (>= 1kg) y hay QR escaneado
            if (nuevoPeso >= 1.0 && formData.nro_op) {
              console.log('[AUTO] ✅ Condiciones cumplidas, auto-grabando...');
              await autoGrabarEImprimir(nuevoPeso);
            } else if (nuevoPeso >= 1.0 && !formData.nro_op) {
              showToast('⚠️ Escanea el QR primero para auto-imprimir', 'error');
            } else if (nuevoPeso > 0 && nuevoPeso < 1.0) {
              showToast('⚠️ Peso muy bajo (< 1kg), no se imprimirá', 'error');
            }
          }
        } catch (err) {
          console.error('Error polling peso:', err);
        }
      }, 500);
    }
    return () => clearInterval(interval);
  }, [listening, peso, formData]);

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
    
    // Try to parse when it looks like a complete QR (has semicolons)
    if (value.includes(';') && value.split(';').length >= 6) {
      await processQrData(value);
    }
  };

  // Handle Enter key from USB scanner
  const handleQrKeyDown = async (e) => {
    if (e.key === 'Enter' && qrInput.trim()) {
      e.preventDefault();
      await processQrData(qrInput);
    }
  };

  // Process QR data
  const processQrData = async (qrString) => {
    try {
      const { data } = await pesajesApi.parseQr(qrString);
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
        showToast('✅ QR escaneado correctamente');
        // Clear QR input after successful scan
        setQrInput('');
      }
    } catch (err) {
      console.error('Error parsing QR:', err);
      showToast('⚠️ Error al leer QR', 'error');
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

  // Auto grabar e imprimir (flujo de 1 botón)
  const autoGrabarEImprimir = async (pesoValue) => {
    console.log('[AUTO] autoGrabarEImprimir llamado con:', { pesoValue, formData });
    
    try {
      const pesajeData = {
        peso_kg: pesoValue,
        ...formData,
        qr_data_original: qrInput
      };
      console.log('[AUTO] Creando pesaje:', pesajeData);
      
      const { data } = await pesajesApi.crear(pesajeData);
      console.log('[AUTO] Pesaje creado con ID:', data.id);
      
      // Imprimir automáticamente
      console.log('[AUTO] Enviando a imprimir ID:', data.id);
      await pesajesApi.imprimir(data.id);
      console.log('[AUTO] ✅ Impresión completada');
      
      showToast('✅ Guardado e impreso automáticamente');
      loadPesajes();
      
      // Show sticker preview
      const preview = await pesajesApi.previewSticker(data.id);
      setStickerPreview(preview.data.preview);
      
    } catch (err) {
      console.error('[AUTO] ❌ Error en autoGrabarEImprimir:', err);
      showToast('❌ Error al guardar/imprimir', 'error');
    }
  };

  const handleGrabar = async () => {
    // Validar peso mínimo
    if (peso < 1.0) {
      showToast('⚠️ Peso inválido (mínimo 1 kg)', 'error');
      return;
    }
    
    // Validar que hay datos del QR
    if (!formData.nro_op) {
      showToast('⚠️ Escanea un QR primero', 'error');
      return;
    }

    try {
      const { data } = await pesajesApi.crear({
        peso_kg: peso,
        ...formData,
        qr_data_original: qrInput
      });
      
      // Imprimir automáticamente
      await pesajesApi.imprimir(data.id);
      showToast('✅ Guardado e impreso correctamente');
      loadPesajes();
      
      // Show sticker preview
      const preview = await pesajesApi.previewSticker(data.id);
      setStickerPreview(preview.data.preview);
      
    } catch (err) {
      showToast('❌ Error al guardar', 'error');
    }
  };

  const handleImprimir = async (id) => {
    try {
      await pesajesApi.imprimir(id);
      showToast('🖨️ Sticker enviado a impresión');
      loadPesajes();
    } catch (err) {
      showToast('Error al imprimir', 'error');
    }
  };

  const handleEliminar = async (id) => {
    if (!confirm('¿Eliminar este pesaje?')) return;
    
    try {
      await pesajesApi.eliminar(id);
      showToast('🗑️ Pesaje eliminado');
      loadPesajes();
    } catch (err) {
      showToast('Error al eliminar', 'error');
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
                <label>📷 Escanear QR</label>
                <input
                  type="text"
                  value={qrInput}
                  onChange={(e) => handleQrInput(e.target.value)}
                  onKeyDown={handleQrKeyDown}
                  placeholder="Escanear con pistola QR..."
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
              <button className="btn btn-secondary" onClick={handleLimpiar}>
                🔄 Limpiar formulario
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
                    <button 
                      className="btn btn-icon btn-danger"
                      onClick={() => handleEliminar(p.id)}
                      title="Eliminar pesaje"
                    >
                      🗑️
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
