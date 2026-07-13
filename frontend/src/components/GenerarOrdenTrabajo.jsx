import { useState, useEffect } from 'react';
import api from '../services/api';
import './GenerarOrdenTrabajo.css';

function GenerarOrdenTrabajo({ formData, onClose }) {
  const [siguiente, setSiguiente] = useState(null);
  const [disponibles, setDisponibles] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [resultado, setResultado] = useState(null);
  const [modoOffline, setModoOffline] = useState(false);
  const [modoReimprimir, setModoReimprimir] = useState(false);
  
  // Estado para anular
  const [showAnular, setShowAnular] = useState(false);
  const [motivoAnular, setMotivoAnular] = useState('');
  const [anulando, setAnulando] = useState(false);
  const [reimprimiendo, setReimprimiendo] = useState(false);
  const [correlativoReimprimir, setCorrelativoReimprimir] = useState('');
  
  // Campos del RDP
  const [ordenData, setOrdenData] = useState({
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
      const { data } = await api.get('/orden-trabajo/siguiente');
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
      const payload = { ...ordenData, nro_orden_trabajo: undefined };
      if (modoOffline) {
         payload.correlativo_manual = siguiente.trim();
      }
      
      const { data } = await api.post('/orden-trabajo/generar', payload);
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
      console.error('Error generando Orden de Trabajo:', err);
      setError(err.response?.data?.error || 'Error generando Orden de Trabajo');
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
      const { data } = await api.post(`/orden-trabajo/anular/${siguiente}`, { motivo: motivoAnular });
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
    setOrdenData(prev => ({
      ...prev,
      [e.target.name]: e.target.value
    }));
  };

  const handleReimprimir = async () => {
    const corr = modoReimprimir ? correlativoReimprimir : resultado?.correlativo;
    if (!corr) return;
    
    setReimprimiendo(true);
    setError(null);
    
    try {
      const { data } = await api.post(`/orden-trabajo/reimprimir/${String(corr)}`);
      setResultado({
        correlativo: data.correlativo,
        impreso: data.impreso,
        reimprimir: true
      });
    } catch (err) {
      console.error('Error reimprimiendo:', err);
      setError(err.response?.data?.error || 'Error reimprimiendo sticker');
    } finally {
      setReimprimiendo(false);
    }
  };

  return (
    <div className="orden-trabajo-overlay">
      <div className="orden-trabajo-modal">
        <div className="orden-trabajo-header">
          <h2>🖨️ Generar Orden de Trabajo (Manual)</h2>
          <button className="orden-trabajo-close" onClick={onClose}>×</button>
        </div>
        
        {/* Toggle modo */}
        <div style={{ display: 'flex', borderBottom: '2px solid var(--border, #333)', marginBottom: '12px' }}>
          <button
            onClick={() => { setModoReimprimir(false); setError(null); setResultado(null); }}
            style={{
              flex: 1, padding: '8px', border: 'none', cursor: 'pointer',
              background: !modoReimprimir ? 'var(--primary, #4f8cff)' : 'transparent',
              color: !modoReimprimir ? '#fff' : 'var(--text-secondary, #aaa)',
              fontWeight: !modoReimprimir ? 700 : 400,
              borderRadius: '6px 6px 0 0', fontSize: '0.9rem'
            }}
          >
            📝 Generar Nuevo
          </button>
          <button
            onClick={() => { setModoReimprimir(true); setError(null); setResultado(null); }}
            style={{
              flex: 1, padding: '8px', border: 'none', cursor: 'pointer',
              background: modoReimprimir ? 'var(--primary, #4f8cff)' : 'transparent',
              color: modoReimprimir ? '#fff' : 'var(--text-secondary, #aaa)',
              fontWeight: modoReimprimir ? 700 : 400,
              borderRadius: '6px 6px 0 0', fontSize: '0.9rem'
            }}
          >
            🖨️ Reimprimir
          </button>
        </div>
        
        {error && <div className="orden-trabajo-error">{error}</div>}
        
        <div className="orden-trabajo-content">
          {modoReimprimir ? (
            /* === MODO REIMPRIMIR === */
            <>
              <div className="orden-trabajo-correlativo" style={{ textAlign: 'center', padding: '16px 0' }}>
                <span className="orden-trabajo-label" style={{ display: 'block', marginBottom: '8px' }}>Número de Correlativo:</span>
                <input
                  type="number"
                  value={correlativoReimprimir}
                  onChange={(e) => setCorrelativoReimprimir(e.target.value)}
                  placeholder="Ej: 30001"
                  style={{ fontSize: '1.4rem', padding: '8px 12px', width: '200px', textAlign: 'center' }}
                />
              </div>
              
              {resultado && (
                <div className="orden-trabajo-resultado">
                  {resultado.impreso ? (
                    <div className="orden-trabajo-success">
                      ✅ Sticker de la Orden de Trabajo <strong>{resultado.correlativo}</strong> reimpreso
                    </div>
                  ) : (
                    <div className="orden-trabajo-error">❌ Error al reimprimir</div>
                  )}
                </div>
              )}
            </>
          ) : (
            /* === MODO GENERAR === */
            <>
          <div className="orden-trabajo-correlativo">
            <div className="orden-trabajo-corr-info" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span className="orden-trabajo-label">Correlativo:</span>
              {modoOffline ? (
                 <input 
                   type="text" 
                   value={siguiente || ''} 
                   onChange={(e) => setSiguiente(e.target.value)}
                   placeholder="Ej: OT-1234"
                   style={{ fontSize: '1.2rem', padding: '4px 8px', width: '150px' }}
                 />
              ) : (
                 <span className="orden-trabajo-value">{siguiente || '---'}</span>
              )}
            </div>
            <div className="orden-trabajo-cache-info">
              {modoOffline ? (
                <span className="orden-trabajo-cache-count" style={{ color: 'var(--warning)' }}>⚠️ Modo Manual</span>
              ) : (
                <span className="orden-trabajo-cache-count">{disponibles} disponibles</span>
              )}
            </div>
          </div>
          
          <div className="orden-trabajo-form">
            <div className="orden-trabajo-field">
              <label>N° Orden de Trabajo (Manual Opcional)</label>
              <input 
                name="nro_op"
                value={ordenData.nro_op}
                onChange={handleChange}
                placeholder="OP-1322"
              />
            </div>
            
            <div className="orden-trabajo-field">
              <label>Turno</label>
              <select name="turno" value={ordenData.turno} onChange={handleChange}>
                <option value="">Seleccionar</option>
                <option value="DIURNO">DIURNO</option>
                <option value="NOCTURNO">NOCTURNO</option>
              </select>
            </div>
            
            <div className="orden-trabajo-field full-width">
              <label>Molde</label>
              <input 
                name="molde"
                value={ordenData.molde}
                onChange={handleChange}
                placeholder="Nombre del molde"
              />
            </div>
            
            <div className="orden-trabajo-field">
              <label>Máquina</label>
              <input 
                name="maquina"
                value={ordenData.maquina}
                onChange={handleChange}
                placeholder="INY-05"
              />
            </div>
            
            <div className="orden-trabajo-field">
              <label>Fecha</label>
              <input 
                type="date"
                name="fecha_ot"
                value={ordenData.fecha_ot}
                onChange={handleChange}
              />
            </div>
            
            <div className="orden-trabajo-field">
              <label>Operador</label>
              <input 
                name="operador"
                value={ordenData.operador}
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

            <div className="orden-trabajo-field">
              <label>Color</label>
              <input 
                name="color"
                value={ordenData.color}
                onChange={handleChange}
                placeholder="Color"
              />
            </div>
          </div>
          
          {/* Dialog para anular */}
          {showAnular && (
            <div className="orden-trabajo-anular-dialog">
              <div className="orden-trabajo-anular-title">⚠️ Anular Correlativo {siguiente}</div>
              <div className="orden-trabajo-field">
                <label>Motivo de anulación *</label>
                <input 
                  value={motivoAnular}
                  onChange={(e) => setMotivoAnular(e.target.value)}
                  placeholder="Ej: Hoja destruida por accidente"
                />
              </div>
              <div className="orden-trabajo-anular-actions">
                <button 
                  className="orden-trabajo-btn orden-trabajo-btn-cancel"
                  onClick={() => setShowAnular(false)}
                >
                  Cancelar
                </button>
                <button 
                  className="orden-trabajo-btn orden-trabajo-btn-danger"
                  onClick={handleAnular}
                  disabled={anulando || !motivoAnular.trim()}
                >
                  {anulando ? '⏳ Anulando...' : '❌ Confirmar Anulación'}
                </button>
              </div>
            </div>
          )}
          
          {resultado && !modoReimprimir && (
            <div className={`orden-trabajo-resultado ${resultado.anulado ? 'anulado' : ''}`}>
              {resultado.anulado ? (
                <div className="orden-trabajo-anulado">
                  ❌ Correlativo {resultado.correlativo} anulado
                  <div className="orden-trabajo-anulado-motivo">Motivo: {resultado.motivo}</div>
                </div>
              ) : (
                <>
                  <div className="orden-trabajo-success">
                    ✅ Orden de Trabajo Generada: <strong>{resultado.correlativo}</strong>
                  </div>
                  {resultado.impreso && (
                    <div className="orden-trabajo-impreso">🖨️ Sticker impreso</div>
                  )}
                  <button 
                    className="orden-trabajo-btn orden-trabajo-btn-secondary" 
                    onClick={handleReimprimir}
                    disabled={reimprimiendo}
                    style={{ marginTop: '8px', width: '100%' }}
                  >
                    {reimprimiendo ? '⏳ Reimprimiendo...' : '🖨️ Reimprimir Sticker'}
                  </button>
                </>
              )}
            </div>
          )}
            </>
          )}
        </div>
        
        <div className="orden-trabajo-actions">
          {modoReimprimir ? (
            <button
              className="orden-trabajo-btn orden-trabajo-btn-primary"
              onClick={handleReimprimir}
              disabled={reimprimiendo || !correlativoReimprimir.trim()}
              style={{ width: '100%' }}
            >
              {reimprimiendo ? '⏳ Reimprimiendo...' : '🖨️ Reimprimir Sticker'}
            </button>
          ) : (
            <>
              <button 
                className="orden-trabajo-btn orden-trabajo-btn-secondary"
                onClick={() => setShowAnular(true)}
                disabled={loading || !siguiente || showAnular}
              >
                ❌ Anular Hoja
              </button>
              <button 
                className="orden-trabajo-btn orden-trabajo-btn-primary"
                onClick={handleGenerar}
                disabled={loading || !siguiente}
              >
                {loading ? '⏳ Generando...' : '🖨️ Generar Orden de Trabajo'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default GenerarOrdenTrabajo;
