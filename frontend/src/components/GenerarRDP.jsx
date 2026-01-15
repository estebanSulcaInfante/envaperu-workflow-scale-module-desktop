import { useState, useEffect } from 'react';
import { rdpApi } from '../services/api';
import './GenerarRDP.css';

function GenerarRDP({ formData, onClose }) {
  const [siguiente, setSiguiente] = useState(null);
  const [disponibles, setDisponibles] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [resultado, setResultado] = useState(null);
  
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
    operador: formData?.operador || ''
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
    } catch (err) {
      console.error('Error obteniendo siguiente:', err);
      setError('Sin conexión al servidor central');
      setSiguiente(null);
    }
  };

  const handleGenerar = async () => {
    if (!siguiente) {
      setError('No hay correlativos disponibles');
      return;
    }
    
    setLoading(true);
    setError(null);
    
    try {
      const { data } = await rdpApi.generar(rdpData);
      setResultado(data);
      setSiguiente(null);
      setDisponibles(data.disponibles_local || 0);
      fetchSiguiente();
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
            <div className="rdp-corr-info">
              <span className="rdp-label">Correlativo:</span>
              <span className="rdp-value">{siguiente || '---'}</span>
            </div>
            <div className="rdp-cache-info">
              <span className="rdp-cache-count">{disponibles} disponibles</span>
            </div>
          </div>
          
          <div className="rdp-form">
            <div className="rdp-row">
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
            </div>
            
            <div className="rdp-field">
              <label>Molde</label>
              <input 
                name="molde"
                value={rdpData.molde}
                onChange={handleChange}
                placeholder="Nombre del molde"
              />
            </div>
            
            <div className="rdp-row">
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
            </div>
            
            <div className="rdp-field">
              <label>Operador</label>
              <input 
                name="operador"
                value={rdpData.operador}
                onChange={handleChange}
                placeholder="Nombre del operador"
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
