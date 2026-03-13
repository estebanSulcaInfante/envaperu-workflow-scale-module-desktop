import React, { useState, useEffect } from 'react';
import { opsApi } from '../services/api';
import './CerrarOps.css';

function CerrarOps() {
  const [opsActivas, setOpsActivas] = useState([]);
  const [opsCerradas, setOpsCerradas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCerradas, setShowCerradas] = useState(false);
  const [toast, setToast] = useState(null);
  
  // Custom modal state
  const [opToClose, setOpToClose] = useState(null);
  const [motivoCierre, setMotivoCierre] = useState('');

  const showToast = (message, type = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const [activasRes, cerradasRes] = await Promise.all([
        opsApi.activas(),
        opsApi.cerradas()
      ]);
      setOpsActivas(activasRes.data || []);
      setOpsCerradas(cerradasRes.data || []);
    } catch (err) {
      console.error('Error cargando OPs:', err);
      showToast('❌ Error al cargar datos', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const initiateCerrar = (op) => {
    setOpToClose(op);
    setMotivoCierre('');
  };

  const confirmCerrar = async () => {
    if (!opToClose) return;
    
    try {
      await opsApi.cerrar({
        nro_op: opToClose.nro_op,
        molde: opToClose.molde,
        motivo: motivoCierre.trim()
      });
      showToast(`🔒 OP ${opToClose.nro_op} cerrada — ya no aparecerá en Avance`);
      
      // Reset modal state and reload
      setOpToClose(null);
      setMotivoCierre('');
      loadData();
    } catch (err) {
      const msg = err.response?.data?.error || 'Error al cerrar OP';
      showToast(`❌ ${msg}`, 'error');
    }
  };

  const cancelCerrar = () => {
    setOpToClose(null);
    setMotivoCierre('');
  };

  const handleReabrir = async (nro_op) => {
    if (!window.confirm(`¿Reabrir OP ${nro_op}? Volverá a aparecer en el avance.`)) return;
    
    try {
      await opsApi.reabrir({ nro_op });
      showToast(`🔓 OP ${nro_op} reabierta`);
      loadData();
    } catch (err) {
      const msg = err.response?.data?.error || 'Error al reabrir OP';
      showToast(`❌ ${msg}`, 'error');
    }
  };

  const formatDate = (isoDate) => {
    if (!isoDate) return '—';
    const date = new Date(isoDate);
    return date.toLocaleString('es-PE', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  };

  if (loading) {
    return <div className="ops-loading">Cargando OPs...</div>;
  }

  return (
    <div className="ops-container">
      {/* Modal Personalizado para Cerrar OP */}
      {opToClose && (
        <div className="custom-modal-overlay">
          <div className="custom-modal">
            <h3>Cerrar OP {opToClose.nro_op}</h3>
            <p>Por favor, ingrese un motivo para cerrar esta OP (Opcional):</p>
            <input 
              type="text" 
              value={motivoCierre} 
              onChange={(e) => setMotivoCierre(e.target.value)} 
              placeholder="Ej: Finalizó el turno"
              autoFocus
            />
            <div className="custom-modal-actions">
              <button className="btn btn-secondary" onClick={cancelCerrar}>Cancelar</button>
              <button className="btn btn-primary" onClick={confirmCerrar}>Cerrar OP</button>
            </div>
          </div>
        </div>
      )}

      {/* OPs Activas */}
      <div className="ops-section">
        <div className="ops-section-header">
          <h2>📋 OPs Activas</h2>
          <span className="ops-count">{opsActivas.length} OP{opsActivas.length !== 1 ? 's' : ''} en avance</span>
        </div>

        {opsActivas.length === 0 ? (
          <div className="ops-empty">
            <p>No hay OPs activas con pesajes registrados.</p>
          </div>
        ) : (
          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>N° OP</th>
                  <th>Molde</th>
                  <th>Total kg</th>
                  <th>Bolsas</th>
                  <th>Último Pesaje</th>
                  <th className="col-action">Acción</th>
                </tr>
              </thead>
              <tbody>
                {opsActivas.map(op => (
                  <tr key={op.nro_op}>
                    <td className="td-op">{op.nro_op}</td>
                    <td>{op.molde || '—'}</td>
                    <td className="td-peso">{op.total_kg?.toFixed(1)}</td>
                    <td className="td-bolsas">{op.total_bolsas}</td>
                    <td className="td-date">{formatDate(op.ultimo_pesaje)}</td>
                    <td className="col-action">
                      <button
                        className="btn btn-warning btn-sm"
                        onClick={() => initiateCerrar(op)}
                      >
                        🔒 Cerrar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* OPs Cerradas */}
      <div className="ops-section cerradas">
        <div
          className="ops-section-header clickable"
          onClick={() => setShowCerradas(!showCerradas)}
        >
          <h2>
            <span className="expand-icon">{showCerradas ? '▼' : '▶'}</span>
            🔒 OPs Cerradas
          </h2>
          <span className="ops-count">{opsCerradas.length} cerrada{opsCerradas.length !== 1 ? 's' : ''}</span>
        </div>

        {showCerradas && (
          opsCerradas.length === 0 ? (
            <div className="ops-empty">
              <p>No hay OPs cerradas.</p>
            </div>
          ) : (
            <div className="ops-table-wrap">
              <table className="ops-table cerradas-table">
                <thead>
                  <tr>
                    <th>N° OP</th>
                    <th>Molde</th>
                    <th>Total kg</th>
                    <th>Bolsas</th>
                    <th>Motivo</th>
                    <th>Fecha Cierre</th>
                    <th className="col-action">Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {opsCerradas.map(op => (
                    <tr key={op.nro_op}>
                      <td className="td-op cerrada">{op.nro_op}</td>
                      <td>{op.molde || '—'}</td>
                      <td>{op.total_kg?.toFixed(1)}</td>
                      <td>{op.total_bolsas}</td>
                      <td className="td-motivo">{op.motivo || '—'}</td>
                      <td className="td-date">{formatDate(op.fecha_cierre)}</td>
                      <td className="col-action">
                        <button
                          className="btn btn-success btn-sm"
                          onClick={() => handleReabrir(op.nro_op)}
                        >
                          🔓 Reabrir
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className={`toast ${toast.type}`}>
          {toast.message}
        </div>
      )}
    </div>
  );
}

export default CerrarOps;
