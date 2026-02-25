import { useState, useEffect } from 'react';
import { rdpApi } from '../services/api';
import './GenerarRDP.css';

function GenerarRDP({ formData, onClose }) {
  const [siguiente, setSiguiente] = useState(null);
  const [disponibles, setDisponibles] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [resultado, setResultado] = useState(null);
  const [modoOffline, setModoOffline] = useState(false);
  
  // Estado para anular
  const [showAnular, setShowAnular] = useState(false);
  const [motivoAnular, setMotivoAnular] = useState('');
  const [anulando, setAnulando] = useState(false);
  
  // Campos del RDP
  const [rdpData, setRdpData] = useState({
    nro_op: formData?.nro_op || '',
    molde: formData?.molde || '',
    maquina: formData?.maquina || '',
    turno: formData?.turno || '',
    fecha_ot: formData?.fecha_orden_trabajo || new Date().toISOString().split('T')[0],
    operador: formData?.operador || '',
    color: formData?.color || ''
  });

  useEffect(() => {
    fetchSiguiente();
  }, []);

  const fetchSiguiente = async () => {
    try {
      const { data } = await rdpApi.getSiguiente();
      setSiguiente(data.siguiente);
      setDisponibles(data.disponibles_local || data.disponibles || 0);
      setError(null);
      setModoOffline(false);
    } catch (err) {
      console.error('Error obteniendo siguiente:', err);
      // Habilitar modo offline para ingreso manual
      setModoOffline(true);
      setSiguiente(''); 
      setDisponibles(0);
      setError('Servidor inaccesible. Modo Offline activado: Ingresa el correlativo manualmente.');
    }
  };

  const handleGenerar = async () => {
    if (!siguiente || siguiente.trim() === '') {
      setError('Debe indicar un correlativo');
      return;
    }
    
    setLoading(true);
    setError(null);
    
    try {
      const payload = { ...rdpData };
      if (modoOffline) {
         payload.correlativo_manual = siguiente.trim();
      }
      
      const { data } = await rdpApi.generar(payload);
      setResultado(data);
      if (!modoOffline) {
          setSiguiente(null);
          setDisponibles(data.disponibles_local || 0);
          fetchSiguiente();
      } else {
          // En offline, lo blanqueamos para que puedan ingresar el sgt
          setSiguiente('');
      }
    } catch (err) {
      console.error('Error generando RDP:', err);
      setError(err.response?.data?.error || 'Error generando RDP');
    } finally {
      setLoading(false);
    }
  };

  const handleAnular = async () => {
    if (!motivoAnular.trim()) {
      setError('Debe ingresar un motivo para anular');
      return;
    }
    
    setAnulando(true);
    setError(null);
    
    try {
      const { data } = await rdpApi.anular(siguiente, motivoAnular);
      setResultado({
        ...data,
        anulado: true
      });
      setShowAnular(false);
      setMotivoAnular('');
      fetchSiguiente();
    } catch (err) {
      console.error('Error anulando:', err);
      setError(err.response?.data?.error || 'Error anulando correlativo');
    } finally {
      setAnulando(false);
    }
  };

  const handleChange = (e) => {
    setRdpData(prev => ({
      ...prev,
      [e.target.name]: e.target.value
    }));
  };

  return (
    <div className="generar-rdp-overlay">
      <div className="generar-rdp-modal">
        <div className="rdp-header">
          <h2>📋 Generar Registro Diario</h2>
          <button className="rdp-close" onClick={onClose}>×</button>
        </div>
        
        {error && <div className="rdp-error">{error}</div>}
        
        <div className="rdp-content">
          <div className="rdp-correlativo">
            <div className="rdp-corr-info" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span className="rdp-label">Correlativo:</span>
              {modoOffline ? (
                 <input 
                   type="text" 
                   value={siguiente || ''} 
                   onChange={(e) => setSiguiente(e.target.value)}
                   placeholder="Ej: OT-1234"
                   style={{ fontSize: '1.2rem', padding: '4px 8px', width: '150px' }}
                 />
              ) : (
                 <span className="rdp-value">{siguiente || '---'}</span>
              )}
            </div>
            <div className="rdp-cache-info">
              {modoOffline ? (
                <span className="rdp-cache-count" style={{ color: 'var(--warning)' }}>⚠️ Modo Manual</span>
              ) : (
                <span className="rdp-cache-count">{disponibles} disponibles</span>
              )}
            </div>
          </div>
          
          <div className="rdp-form">
            <div className="rdp-field">
              <label>N° OP</label>
              <input 
                name="nro_op"
                value={rdpData.nro_op}
                onChange={handleChange}
                placeholder="OP-1322"
              />
            </div>
            
            <div className="rdp-field">
              <label>Turno</label>
              <select name="turno" value={rdpData.turno} onChange={handleChange}>
                <option value="">Seleccionar</option>
                <option value="DIURNO">DIURNO</option>
                <option value="NOCTURNO">NOCTURNO</option>
              </select>
            </div>
            
            <div className="rdp-field full-width">
              <label>Molde</label>
              <input 
                name="molde"
                value={rdpData.molde}
                onChange={handleChange}
                placeholder="Nombre del molde"
              />
            </div>
            
            <div className="rdp-field">
              <label>Máquina</label>
              <input 
                name="maquina"
                value={rdpData.maquina}
                onChange={handleChange}
                placeholder="INY-05"
              />
            </div>
            
            <div className="rdp-field">
              <label>Fecha</label>
              <input 
                type="date"
                name="fecha_ot"
                value={rdpData.fecha_ot}
                onChange={handleChange}
              />
            </div>
            
            <div className="rdp-field">
              <label>Operador</label>
              <input 
                name="operador"
                value={rdpData.operador}
                onChange={handleChange}
                placeholder="Nombre del operador"
                list="operadores-rdp-list"
              />
              <datalist id="operadores-rdp-list">
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

            <div className="rdp-field">
              <label>Color</label>
              <input 
                name="color"
                value={rdpData.color}
                onChange={handleChange}
                placeholder="Color"
              />
            </div>
          </div>
          
          {/* Dialog para anular */}
          {showAnular && (
            <div className="rdp-anular-dialog">
              <div className="rdp-anular-title">⚠️ Anular Correlativo {siguiente}</div>
              <div className="rdp-field">
                <label>Motivo de anulación *</label>
                <input 
                  value={motivoAnular}
                  onChange={(e) => setMotivoAnular(e.target.value)}
                  placeholder="Ej: Hoja destruida por accidente"
                />
              </div>
              <div className="rdp-anular-actions">
                <button 
                  className="rdp-btn rdp-btn-cancel"
                  onClick={() => setShowAnular(false)}
                >
                  Cancelar
                </button>
                <button 
                  className="rdp-btn rdp-btn-danger"
                  onClick={handleAnular}
                  disabled={anulando || !motivoAnular.trim()}
                >
                  {anulando ? '⏳ Anulando...' : '❌ Confirmar Anulación'}
                </button>
              </div>
            </div>
          )}
          
          {resultado && (
            <div className={`rdp-resultado ${resultado.anulado ? 'anulado' : ''}`}>
              {resultado.anulado ? (
                <div className="rdp-anulado">
                  ❌ Correlativo {resultado.correlativo} anulado
                  <div className="rdp-anulado-motivo">Motivo: {resultado.motivo}</div>
                </div>
              ) : (
                <>
                  <div className="rdp-success">
                    ✅ RDP Generado: <strong>{resultado.correlativo}</strong>
                  </div>
                  {resultado.impreso && (
                    <div className="rdp-impreso">🖨️ Sticker impreso</div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
        
        <div className="rdp-actions">
          <button 
            className="rdp-btn rdp-btn-secondary"
            onClick={() => setShowAnular(true)}
            disabled={loading || !siguiente || showAnular}
          >
            ❌ Anular Hoja
          </button>
          <button 
            className="rdp-btn rdp-btn-primary"
            onClick={handleGenerar}
            disabled={loading || !siguiente}
          >
            {loading ? '⏳ Generando...' : '🖨️ Generar e Imprimir'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default GenerarRDP;
