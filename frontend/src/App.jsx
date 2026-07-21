import { useState, useEffect, useRef } from 'react';
import { pesajesApi, balanzaApi, healthApi, syncApi, ordenTrabajoApi } from './services/api';
import { createCaptureCoordinator, submitCaptureAndPrint } from './services/captureFlow';
import socket from './services/socket';
import CaptureResultNotice from './components/CaptureResultNotice';
import ExportarExcel from './components/ExportarExcel';
import AvanceDashboard from './components/AvanceDashboard';
import GestionPesajes from './components/GestionPesajes';
import GenerarOrdenTrabajo from './components/GenerarOrdenTrabajo';
import CerrarOps from './components/CerrarOps';
import CentralStatusBadge from './components/CentralStatusBadge';
import { calculateWeightAdjustment } from './utils/weightAdjustment';

function App() {
  // Connection state
  const [connected, setConnected] = useState(false);
  const [listening, setListening] = useState(false);
  const [centralState, setCentralState] = useState('CENTRAL_NOT_PROVISIONED');
  
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
    color: '',
    pieza_sku: '',
    pieza_nombre: '',
    peso_unitario_teorico: '',
    descuento_porcentaje: '0'
  });
  
  // Piezas disponibles para el molde actual (del cache)
  const [piezasDisponibles, setPiezasDisponibles] = useState([]);
  
  // Pesajes list
  const [pesajes, setPesajes] = useState([]);
  
  // UI state
  const [toast, setToast] = useState(null);
  const [stickerPreview, setStickerPreview] = useState(null);
  const [showExcelModal, setShowExcelModal] = useState(false);
  const [generandoOT, setGenerandoOT] = useState(false);
  const [activeTab, setActiveTab] = useState('crear-ot');
  const [cooldown, setCooldown] = useState(false);
  const [captureInFlight, setCaptureInFlight] = useState(false);
  const [captureResult, setCaptureResult] = useState(null);
  const [retryingPrint, setRetryingPrint] = useState(false);
  const captureInFlightRef = useRef(false);
  const captureCoordinatorRef = useRef(null);
  if (!captureCoordinatorRef.current) {
    captureCoordinatorRef.current = createCaptureCoordinator();
  }
  const weightAdjustment = calculateWeightAdjustment(
    peso,
    formData.descuento_porcentaje,
  );

  // Load status and pesajes on mount
  useEffect(() => {
    checkStatus();
    checkCentralStatus();
    loadPesajes();
    
    // Auto-llenar fecha con fecha actual
    const today = new Date().toISOString().split('T')[0];
    setFormData(prev => ({
      ...prev,
      fecha_orden_trabajo: today
    }));
  }, []);

  useEffect(() => {
    const interval = window.setInterval(checkCentralStatus, 30000);
    return () => window.clearInterval(interval);
  }, []);

  // WebSocket: escuchar peso en vivo desde la balanza
  useEffect(() => {
    const handlePeso = (data) => {
      if (data.peso_kg !== null) {
        setPeso(data.peso_kg);
      }
    };
    socket.on('peso', handlePeso);
    return () => socket.off('peso', handlePeso);
  }, []);

  // WebSocket: escuchar actualizaciones de pesajes
  useEffect(() => {
    const handlePesajesUpdated = () => {
      loadPesajes();
    };
    socket.on('pesajes_updated', handlePesajesUpdated);
    return () => socket.off('pesajes_updated', handlePesajesUpdated);
  }, []);

  // WebSocket: escuchar estado de conexión de la balanza en tiempo real
  useEffect(() => {
    const handleBalanzaStatus = (data) => {
      const wasConnected = connected;
      setConnected(data.connected);
      if (data.listening !== undefined) {
        setListening(data.listening);
      }
      // Mostrar toast solo cuando hay un cambio de estado
      if (data.connected && !wasConnected) {
        showToast('✅ Balanza reconectada');
      } else if (!data.connected && wasConnected) {
        showToast('⚠️ Balanza desconectada', 'error');
      }
    };
    socket.on('balanza_status', handleBalanzaStatus);
    return () => socket.off('balanza_status', handleBalanzaStatus);
  }, [connected]);

  // F2 key listener para aceptar peso
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'F2' && activeTab === 'pesar') {
        e.preventDefault();
        handleAceptarPeso();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [peso, formData, cooldown, captureInFlight, activeTab]);

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
        const moldeNombre = data.data.molde || '';
        const todayStr = new Date().toLocaleDateString('en-CA'); // Formato YYYY-MM-DD local
        
        setFormData(prev => ({
          ...prev,
          molde: moldeNombre,
          maquina: data.data.maquina || '',
          nro_op: data.data.nro_op || '',
          turno: data.data.turno || '',
          fecha_orden_trabajo: data.data.fecha_orden_trabajo || todayStr,
          nro_orden_trabajo: data.data.nro_orden_trabajo || '',
          peso_unitario_teorico: data.data.peso_unitario_teorico || '',
          pieza_sku: '',
          pieza_nombre: '',
          descuento_porcentaje: '0'
        }));
        
        // Buscar piezas cacheadas para este molde
        if (moldeNombre) {
          try {
            const { data: piezasData } = await syncApi.getCachedPiezas(moldeNombre);
            setPiezasDisponibles(piezasData || []);
          } catch (err) {
            console.log('No hay piezas cacheadas para este molde');
            setPiezasDisponibles([]);
          }
        }
        
        showToast('✅ QR escaneado correctamente');
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

  // Aceptar peso con F2 (reemplaza al auto-grab)
  const handleAceptarPeso = async () => {
    if (cooldown || captureInFlightRef.current) {
      showToast('⏳ Espera unos segundos...', 'error');
      return;
    }
    const adjustment = calculateWeightAdjustment(
      peso,
      formData.descuento_porcentaje,
    );
    if (!adjustment.valid) {
      showToast('El descuento debe estar entre 0% y menos de 100%', 'error');
      return;
    }
    if (adjustment.attributableWeightKg < 1.0) {
      showToast('⚠️ Peso inválido (mínimo 1 kg)', 'error');
      return;
    }
    if (!formData.nro_op) {
      showToast('⚠️ Escanea un QR primero', 'error');
      return;
    }

    captureInFlightRef.current = true;
    setCaptureInFlight(true);
    setCooldown(true);
    setTimeout(() => setCooldown(false), 3000);

    const captureFormData = { ...formData };
    delete captureFormData.descuento_porcentaje;
    const session = captureCoordinatorRef.current.begin({
      ...captureFormData,
      peso_kg: adjustment.attributableWeightKg,
      peso_bruto_kg: adjustment.grossWeightKg,
      fraccion_descuento: adjustment.discountFraction,
      qr_data_original: qrInput
    });

    try {
      const result = await submitCaptureAndPrint({
        session,
        captureRequest: pesajesApi.capturar,
        printRequest: pesajesApi.imprimirCaptura,
      });

      captureCoordinatorRef.current.complete(session.captureId);
      setCaptureResult(result);
      await loadPesajes();

      if (result.status === 'SAVED_PRINTED') {
        showToast(`✅ Pesaje #${result.pesaje.id} guardado e impreso`);
      } else {
        showToast('Pesaje guardado; impresión fallida', 'error');
      }

      try {
        const preview = await pesajesApi.previewSticker(result.pesaje.id);
        setStickerPreview(preview.data.preview);
      } catch (previewError) {
        console.warn('[F2] No se pudo cargar la vista previa:', previewError);
      }
    } catch (err) {
      console.error('[F2] ❌ Error:', err);
      const isConflict = err.response?.data?.code === 'IDEMPOTENCY_CONFLICT';
      showToast(
        isConflict
          ? 'Conflicto de captura. Requiere revisión del supervisor.'
          : 'No se confirmó el guardado. F2 reintentará la misma captura.',
        'error'
      );
    } finally {
      captureInFlightRef.current = false;
      setCaptureInFlight(false);
    }
  };

  const checkCentralStatus = async () => {
    try {
      const { data } = await healthApi.ready();
      setCentralState(data.central?.state || 'CENTRAL_NOT_PROVISIONED');
    } catch (err) {
      console.error('Error checking central status:', err);
      setCentralState('CENTRAL_UNREACHABLE');
    }
  };

  const handleRetryCapturePrint = async (captureId) => {
    if (retryingPrint) return;
    setRetryingPrint(true);
    try {
      const { data } = await pesajesApi.imprimirCaptura(captureId);
      setCaptureResult({
        status: data.status,
        printStatus: data.status,
        pesaje: data.pesaje,
        attempt: data.print_attempt,
      });

      if (data.status === 'SAVED_PRINTED') {
        showToast(`✅ Etiqueta del pesaje #${data.pesaje.id} impresa`);
      } else {
        showToast('La impresión volvió a fallar; el pesaje sigue guardado.', 'error');
      }
      await loadPesajes();
    } catch (err) {
      showToast('No se pudo confirmar la impresión; el pesaje sigue guardado.', 'error');
    } finally {
      setRetryingPrint(false);
    }
  };

  const handleImprimir = async (id) => {
    try {
      const { data } = await pesajesApi.imprimir(id);
      if (data.pesaje?.capture_id) {
        setCaptureResult({
          status: data.status,
          printStatus: data.status,
          pesaje: data.pesaje,
          attempt: data.print_attempt,
        });
      }
      if (data.status === 'SAVED_PRINTED') {
        showToast('🖨️ Sticker enviado a impresión');
      } else {
        showToast('Pesaje guardado; impresión fallida', 'error');
      }
      await loadPesajes();
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
      peso_unitario_teorico: '',
      operador: '',
      color: '',
      pieza_sku: '',
      pieza_nombre: '',
      descuento_porcentaje: '0'
    });
    setStickerPreview(null);
  };

  // Generar e imprimir sticker de OT directamente desde el formulario
  const handleGenerarOT = async () => {
    if (!formData.nro_orden_trabajo || !formData.nro_orden_trabajo.trim()) {
      showToast('⚠️ Ingresa un Nro de Orden de Trabajo', 'error');
      return;
    }
    if (!formData.nro_op) {
      showToast('⚠️ Escanea una OP primero', 'error');
      return;
    }
    
    setGenerandoOT(true);
    try {
      const payload = {
        correlativo_manual: formData.nro_orden_trabajo.trim(),
        nro_op: formData.nro_op,
        molde: formData.molde,
        maquina: formData.maquina,
        turno: formData.turno,
        fecha_ot: formData.fecha_orden_trabajo,
        operador: formData.operador,
        color: formData.color,
        peso_unitario_teorico: formData.peso_unitario_teorico
      };

      const { data } = await ordenTrabajoApi.generar(payload);
      if (data.impreso) {
        showToast(`✅ Sticker de OT "${formData.nro_orden_trabajo}" impreso`);
      } else {
        showToast(`✅ OT "${formData.nro_orden_trabajo}" generada (sin impresora)`);
      }
    } catch (err) {
      const msg = err.response?.data?.error || 'Error al generar OT';
      showToast(`❌ ${msg}`, 'error');
    } finally {
      setGenerandoOT(false);
    }
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
          <CentralStatusBadge state={centralState} />
          <button 
            className="btn btn-secondary"
            onClick={() => setShowExcelModal(true)}
            style={{ marginRight: '12px' }}
          >
            📊 Exportar Excel
          </button>

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

      {/* Tab Navigation */}
      <div className="tab-nav">
        <button 
          className={`tab-btn ${activeTab === 'crear-ot' ? 'active' : ''}`}
          onClick={() => setActiveTab('crear-ot')}
        >
          📋 Crear OT
        </button>
            <button 
              className={`tab-btn ${activeTab === 'pesar' ? 'active' : ''}`}
              onClick={() => setActiveTab('pesar')}
            >
              2. Pesar OPs
            </button>
            <button 
              className={`tab-btn ${activeTab === 'avance' ? 'active' : ''}`}
              onClick={() => setActiveTab('avance')}
            >
              3. 📈 Avance
            </button>
            <button 
              className={`tab-btn ${activeTab === 'gestion' ? 'active' : ''}`}
              onClick={() => setActiveTab('gestion')}
            >
              📦 Gestión
            </button>
            <button 
              className={`tab-btn ${activeTab === 'cerrar-ops' ? 'active' : ''}`}
              onClick={() => setActiveTab('cerrar-ops')}
            >
              🔒 Cerrar OPs
            </button>
          </div>

      {/* ========== TAB 1: CREAR OT ========== */}
      {activeTab === 'crear-ot' && (
        <main className="main-content">
          <div className="panel">
            <div className="panel-header">📋 CREAR ORDEN DE TRABAJO</div>
            <div className="panel-body">
              
              {/* QR Input - Escanear OP */}
              <div className="qr-section">
                <div className="qr-input-group">
                  <label>📷 Escanear QR de Orden de Producción</label>
                  <input
                    type="text"
                    value={qrInput}
                    onChange={(e) => handleQrInput(e.target.value)}
                    onKeyDown={handleQrKeyDown}
                    placeholder={formData.nro_op ? "✅ QR escaneado - Escanear otra OP..." : "⏳ Esperando escaneo de QR..."}
                    autoFocus
                    className={!formData.nro_op ? 'input-highlight' : ''}
                  />
                  {!formData.nro_op && (
                    <small className="input-hint">👆 Escanea el QR de la hoja de OP aquí</small>
                  )}
                </div>
              </div>

              {/* Form Fields para OT */}
              <div className="form-grid">
                <div className="form-group">
                  <label>N° OP</label>
                  <input type="text" name="nro_op" value={formData.nro_op} disabled />
                </div>
                <div className="form-group">
                  <label>Molde</label>
                  <input type="text" name="molde" value={formData.molde} disabled />
                </div>
                <div className="form-group">
                  <label>Máquina</label>
                  <input type="text" name="maquina" value={formData.maquina} disabled />
                </div>
                <div className="form-group">
                  <label>Turno</label>
                  <select name="turno" value={formData.turno} onChange={handleInputChange}>
                    <option value="">Seleccionar...</option>
                    <option value="DIURNO">DIURNO</option>
                    <option value="NOCTURNO">NOCTURNO</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>Fecha</label>
                  <input
                    type="date"
                    name="fecha_orden_trabajo"
                    value={formData.fecha_orden_trabajo}
                    onChange={handleInputChange}
                  />
                </div>
                <div className="form-group">
                  <label>Nro Orden de Trabajo (Correlativo)</label>
                  <input
                    type="text"
                    name="nro_orden_trabajo"
                    value={formData.nro_orden_trabajo}
                    onChange={handleInputChange}
                    placeholder="Ej: 054231"
                    className="highlight"
                  />
                </div>
              </div>

              {/* Action Buttons */}
              <div className="actions-row">
                <button 
                  className="btn btn-primary"
                  onClick={handleGenerarOT}
                  disabled={generandoOT || !formData.nro_orden_trabajo || !formData.nro_op}
                  style={{ marginRight: '12px' }}
                >
                  {generandoOT ? '⏳ Generando...' : '🖨️ Imprimir Sticker de OT'}
                </button>
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
        </main>
      )}

      {/* TAB 3: AVANCE DASHBOARD */}
      {activeTab === 'avance' && (
        <main className="main-content avance-full">
          <AvanceDashboard />
        </main>
      )}

      {/* TAB 4: GESTIÓN PESAJES */}
      {activeTab === 'gestion' && (
        <main className="main-content avance-full">
          <GestionPesajes />
        </main>
      )}

      {/* TAB 5: CERRAR OPs */}
      {activeTab === 'cerrar-ops' && (
        <main className="main-content avance-full">
          <CerrarOps />
        </main>
      )}

      {/* ========== TAB 2: PESAR ========== */}
      {activeTab === 'pesar' && (
        <main className="main-content">
          {/* Left Panel - Pesaje Form */}
          <div className="panel">
            <div className="panel-header">⚖️ REGISTRO DE PESAJE</div>
            <div className="panel-body">

              {/* Status Banner */}
              {!connected && (
                <div className="status-banner warning" style={{ margin: '0 0 16px 0', borderRadius: '8px' }}>
                  <span className="banner-icon">⚠️</span>
                  <span className="banner-text">
                    <strong>Paso 1:</strong> Conecta la balanza
                  </span>
                  <button className="btn btn-sm btn-primary" onClick={handleConnect}>
                    🔌 Conectar
                  </button>
                </div>
              )}

              {/* QR Input - Escanear OT ya impresa */}
              <div className="qr-section">
                <div className="qr-input-group">
                  <label>📷 Escanear QR de Orden de Trabajo (OT impresa)</label>
                  <input
                    type="text"
                    value={qrInput}
                    onChange={(e) => handleQrInput(e.target.value)}
                    onKeyDown={handleQrKeyDown}
                    placeholder={formData.nro_orden_trabajo ? `✅ OT ${formData.nro_orden_trabajo} cargada` : "⏳ Escanear QR de la OT..."}
                    autoFocus
                    className={!formData.nro_orden_trabajo ? 'input-highlight' : ''}
                  />
                  {!formData.nro_orden_trabajo && (
                    <small className="input-hint">👆 Escanea el sticker QR de la OT impresa para cargar los datos</small>
                  )}
                </div>
              </div>

              {/* Datos heredados de la OT (solo lectura) */}
              {formData.nro_op && (
                <div style={{ background: 'var(--bg-secondary, #f0f4f8)', borderRadius: '8px', padding: '12px 16px', marginBottom: '16px', fontSize: '0.9rem', color: 'var(--text-secondary, #666)' }}>
                  <strong>OT:</strong> {formData.nro_orden_trabajo || '—'} &nbsp;|&nbsp;
                  <strong>OP:</strong> {formData.nro_op} &nbsp;|&nbsp;
                  <strong>Molde:</strong> {formData.molde} &nbsp;|&nbsp;
                  <strong>Máquina:</strong> {formData.maquina} &nbsp;|&nbsp;
                  <strong>Turno:</strong> {formData.turno || '—'}
                </div>
              )}

              {/* Form Fields exclusivos del pesaje */}
              <div className="form-grid">
                <div className="form-group">
                  <label>Operador</label>
                  <input
                    type="text"
                    name="operador"
                    value={formData.operador}
                    onChange={handleInputChange}
                    placeholder="Nombre del operador"
                    list="operadores-list"
                  />
                  <datalist id="operadores-list">
                    <option value="Almea Zapata Maria Jose" />
                    <option value="Pinedo Nelson" />
                    <option value="Cedeño Cedeño Juan Carlos" />
                    <option value="Sulca Cahuana Carlos" />
                    <option value="Pinedo Cruces Jose Luis" />
                    <option value="Rengifo Chumbe Jose Luis" />
                    <option value="Zapata Guatarama Crisalida" />
                    <option value="Villamizar Said" />
                    <option value="Malaver Nestor" />
                    <option value="Henriquez Silfredo" />
                    <option value="Vilchez Marjorie" />
                    <option value="Cruces Juana" />
                    <option value="Linariz Yerica Isabel" />
                    <option value="Casablanca Jair" />
                    <option value="Gonzalez Perez Josder Johan" />
                    <option value="Requena Gabriel Armando" />
                    <option value="Calderas Algimiro" />
                    <option value="Luna Jheoriannys" />
                    <option value="Murga Cynthia" />
                  </datalist>
                </div>
                <div className="form-group">
                  <label>Color de pieza</label>
                  <input
                    type="text"
                    name="color"
                    value={formData.color}
                    onChange={handleInputChange}
                    placeholder="Color de pieza"
                    list="colores-list"
                  />
                  <datalist id="colores-list">
                    <option value="AMARILLO" />
                    <option value="ANARANJADO" />
                    <option value="AZUL" />
                    <option value="AZURE" />
                    <option value="BLANCO" />
                    <option value="CARNE" />
                    <option value="CELESTE" />
                    <option value="CREMA" />
                    <option value="FUCSIA" />
                    <option value="LILA" />
                    <option value="LILA BEBE" />
                    <option value="MARRON" />
                    <option value="MELON" />
                    <option value="NEGRO" />
                    <option value="PLOMO" />
                    <option value="ROJO" />
                    <option value="ROSADO" />
                    <option value="SANDIA" />
                    <option value="TRANSPARENTE" />
                    <option value="TURQUESA" />
                    <option value="VERDE" />
                  </datalist>
                </div>

                <div className="form-group">
                  <label htmlFor="descuento-porcentaje">Descuento ajeno a la pieza (%)</label>
                  <input
                    id="descuento-porcentaje"
                    type="number"
                    name="descuento_porcentaje"
                    value={formData.descuento_porcentaje}
                    onChange={handleInputChange}
                    min="0"
                    max="99.999"
                    step="0.1"
                    inputMode="decimal"
                    aria-describedby="descuento-porcentaje-ayuda"
                    aria-invalid={!weightAdjustment.valid}
                  />
                  <small id="descuento-porcentaje-ayuda" className="field-hint">
                    Ejemplo: 10 descuenta el 10% del peso mostrado por la balanza.
                  </small>
                </div>
                
                {/* Selector de Pieza/Componente */}
                {piezasDisponibles.length > 0 && (
                  <div className="form-group">
                    <label>Pieza / Componente</label>
                    <select
                      value={formData.pieza_sku}
                      onChange={(e) => {
                        const selectedPieza = piezasDisponibles.find(p => p.pieza_sku === e.target.value);
                        setFormData(prev => ({
                          ...prev,
                          pieza_sku: e.target.value,
                          pieza_nombre: selectedPieza?.pieza_nombre || ''
                        }));
                      }}
                      style={{ borderColor: formData.pieza_sku ? 'var(--success)' : 'var(--warning)' }}
                    >
                      <option value="">Pieza Completa (Kit)</option>
                      {piezasDisponibles.map(p => (
                        <option key={p.pieza_sku} value={p.pieza_sku}>
                          {p.pieza_nombre} ({p.tipo})
                        </option>
                      ))}
                    </select>
                    <small style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                      Selecciona qué componente estás pesando
                    </small>
                  </div>
                )}
              </div>

              {/* Weight Display */}
              <div className="weight-display-container">
                <div className="weight-display">
                  <span className="weight-label">Peso de balanza</span>
                  <span className="weight-value">{peso.toFixed(3)}</span>
                  <span className="weight-unit">kg</span>
                  <div className="weight-status">
                    {!listening
                      ? 'Conectar balanza para capturar peso'
                      : captureInFlight
                        ? 'Guardando captura...'
                        : cooldown
                        ? '⏳ Cooldown... espera'
                        : '📡 En vivo — Presiona F2 para aceptar'
                    }
                  </div>
                </div>
                <div
                  className={`weight-adjustment-summary ${weightAdjustment.discountPercentage > 0 ? 'active' : ''} ${!weightAdjustment.valid ? 'invalid' : ''}`}
                  role="status"
                >
                  <span>Peso atribuible a la pieza</span>
                  <strong>
                    {weightAdjustment.valid
                      ? `${weightAdjustment.attributableWeightKg.toFixed(3)} kg`
                      : 'Descuento inválido'}
                  </strong>
                  <small>
                    {weightAdjustment.valid && weightAdjustment.discountPercentage > 0
                      ? `Se descuentan ${weightAdjustment.discountedWeightKg.toFixed(3)} kg (${weightAdjustment.discountPercentage}%).`
                      : 'Sin descuento aplicado.'}
                  </small>
                </div>
                {activeTab === 'pesar' && listening && !cooldown && !captureInFlight && weightAdjustment.valid && weightAdjustment.attributableWeightKg >= 1.0 && formData.nro_op && (
                  <button
                    className="btn btn-primary"
                    onClick={handleAceptarPeso}
                    aria-label={`Aceptar ${weightAdjustment.attributableWeightKg.toFixed(3)} kg`}
                    style={{ marginTop: '12px', fontSize: '1.1rem', padding: '12px 32px' }}
                  >
                    ⏎ Aceptar Peso (F2)
                  </button>
                )}
              </div>

              <CaptureResultNotice
                result={captureResult}
                onRetryPrint={handleRetryCapturePrint}
                retrying={retryingPrint}
              />

              {/* Action Buttons */}
              <div className="actions-row">
                <button className="btn btn-secondary" onClick={handleLimpiar}>
                  🔄 Limpiar formulario
                </button>
              </div>
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
                      <span className="peso">{p.peso_kg.toFixed(3)} kg</span>
                      <span className="meta">
                        {p.nro_orden_trabajo ? `OT ${p.nro_orden_trabajo} • ` : ''}{p.molde || 'Sin molde'} • {p.nro_op || ''} • {formatDate(p.fecha_hora)}
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
      )}

      {/* Toast */}
      {toast && (
        <div className={`toast ${toast.type}`}>
          {toast.message}
        </div>
      )}
      


      {/* Modal Exportar Excel */}
      {showExcelModal && (
        <ExportarExcel 
          onClose={() => setShowExcelModal(false)}
        />
      )}
    </div>
  );
}

export default App;
