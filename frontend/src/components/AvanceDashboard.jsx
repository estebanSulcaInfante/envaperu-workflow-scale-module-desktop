import React, { useState, useEffect } from 'react';
import { avanceApi } from '../services/api';
import socket from '../services/socket';
import './AvanceDashboard.css';

function AvanceDashboard() {
  const [resumen, setResumen] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [bigMode, setBigMode] = useState(false); // Toggle para la vista grande

  const loadData = async () => {
    try {
      const { data } = await avanceApi.resumen();
      setResumen(data);
      setError(null);
    } catch (err) {
      console.error('Error cargando avance:', err);
      setError('No se pudo cargar el avance. Verifica la conexión.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();

    // Escuchar actualizaciones en tiempo real via WebSocket
    const handlePesajesUpdated = () => {
      console.log('[WS] Avance: pesaje detectado, actualizando...');
      loadData();
    };

    socket.on('pesajes_updated', handlePesajesUpdated);
    return () => socket.off('pesajes_updated', handlePesajesUpdated);
  }, []);

  if (loading) return <div className="avance-loading">Cargando avance...</div>;
  if (error) return <div className="avance-error">{error}</div>;
  if (!resumen || resumen.items.length === 0) {
    return (
      <div className="avance-empty">
        <h3>📊 No hay pesajes registrados hoy</h3>
        <p>Los datos aparecerán aquí cuando comiences a pesar.</p>
      </div>
    );
  }

  // Vista "Big Mode" (Para pantallas grandes, foco en PESO TOTAL)
  if (bigMode) {
    return (
      <div className="avance-container big-mode">
        <div className="avance-header">
          <h2>📊 AVANCE EN VIVO</h2>
          <button className="btn btn-secondary" onClick={() => setBigMode(false)}>
            Ver Detalles
          </button>
        </div>
        
        <div className="big-cards-grid">
          {resumen.items.map((item, idx) => (
            <div key={idx} className="big-card">
              <div className="bc-header">
                <span className="bc-ot">OT {item.nro_orden_trabajo || 'S/N'}</span>
                <span className="bc-op">{item.nro_op}</span>
              </div>
              <div className="bc-molde">{item.molde}</div>
              
              <div className="bc-weight-container">
                <div className="bc-weight-value">{item.total_peso_kg.toFixed(1)}</div>
                <div className="bc-weight-unit">KG</div>
              </div>
              
              <div className="bc-footer">
                <div className="bc-stat">
                  <span className="label">CAJAS:</span>
                  <span className="value">{item.total_pesajes}</span>
                </div>
                {item.unidades_estimadas > 0 && (
                  <div className="bc-stat highlight">
                    <span className="label">UNID. EST:</span>
                    <span className="value">~{item.unidades_estimadas}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Vista "Standard Mode" (Lista detallada)
  return (
    <div className="avance-container">
      <div className="avance-header">
        <h2>📊 Resumen de Avance ({resumen.fecha})</h2>
        <div className="header-actions">
          <span className="total-global">Total Día: <strong>{resumen.total_global_kg.toFixed(1)} kg</strong> ({resumen.total_registros} cajas)</span>
          <button className="btn btn-primary" onClick={() => setBigMode(true)}>
            📺 Vista Pantalla Grande
          </button>
        </div>
      </div>

      <div className="avance-grid">
        {resumen.items.map((item, idx) => (
          <div key={idx} className="avance-card">
            <div className="ac-header">
              <div className="ac-title">
                <span className="ac-ot">OT: {item.nro_orden_trabajo || '—'}</span>
                <span className="ac-op">OP: {item.nro_op || '—'}</span>
              </div>
              <span className="ac-turno badge">{item.turno || 'SinTurno'}</span>
            </div>
            
            <div className="ac-body">
              <div className="info-row"><strong>Molde:</strong> {item.molde || '—'}</div>
              <div className="info-row"><strong>Máquina:</strong> {item.maquina || '—'}</div>
              {item.peso_unitario_teorico > 0 && (
                <div className="info-row" style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                  Peso Unit: {item.peso_unitario_teorico}g
                </div>
              )}
            </div>

            <div className="ac-stats">
              <div className="stat-box primary">
                <span className="stat-value">{item.total_peso_kg.toFixed(1)}</span>
                <span className="stat-label">Kilos Totales</span>
              </div>
              <div className="stat-box secondary">
                <span className="stat-value">{item.total_pesajes}</span>
                <span className="stat-label">Pesajes (Cajas)</span>
              </div>
              {item.unidades_estimadas > 0 && (
                <div className="stat-box accent">
                  <span className="stat-value">~{item.unidades_estimadas}</span>
                  <span className="stat-label">Unid. Estimadas</span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default AvanceDashboard;
