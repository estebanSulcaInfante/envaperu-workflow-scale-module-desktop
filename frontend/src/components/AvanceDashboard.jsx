import React, { useState, useEffect } from 'react';
import { avanceApi } from '../services/api';
import socket from '../services/socket';
import './AvanceDashboard.css';

// Mapa de colores: hex real o 'pattern' para colores abstractos
const COLOR_MAP = {
  'AMARILLO':     '#FFD600',
  'ANARANJADO':   '#FF6D00',
  'AZUL':         '#1565C0',
  'AZURE':        '#039BE5',
  'BLANCO':       '#F5F5F5',
  'CELESTE':      '#4FC3F7',
  'FUCSIA':       '#D81B60',
  'LILA':         '#7E57C2',
  'LILA BEBE':    '#CE93D8',
  'MARRON':       '#6D4C41',
  'NEGRO':        '#212121',
  'PLOMO':        '#9E9E9E',
  'ROJO':         '#D32F2F',
  'ROSADO':       '#F48FB1',
  'TURQUESA':     '#00897B',
  'VERDE':        '#2E7D32',
  // Colores abstractos → patrón checkered
  'NATURAL':      'pattern',
  'TRANSPARENTE': 'pattern',
  'CARNE':        'pattern',
  'CREMA':        'pattern',
  'MELON':        'pattern',
  'SANDIA':       'pattern',
};

// Componente de punto de color
const ColorDot = ({ color }) => {
  const hex = COLOR_MAP[color];
  if (hex === 'pattern') {
    return <span className="color-dot checkered" title={color} />;
  }
  return (
    <span
      className="color-dot"
      style={{ backgroundColor: hex || '#BDBDBD' }}
      title={color}
    />
  );
};

function AvanceDashboard() {
  const [resumen, setResumen] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [bigMode, setBigMode] = useState(false);
  const [expanded, setExpanded] = useState({});

  const loadData = async () => {
    try {
      const { data } = await avanceApi.resumen();
      setResumen(data);
      setError(null);
      if (data.grupos) {
        setExpanded(prev => {
          const merged = {};
          data.grupos.forEach((g, i) => {
            const key = `${g.molde}|${g.color}`;
            merged[key] = prev[key] !== undefined ? prev[key] : true;
          });
          return merged;
        });
      }
    } catch (err) {
      console.error('Error cargando avance:', err);
      setError('No se pudo cargar el avance.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const handler = () => loadData();
    socket.on('pesajes_updated', handler);
    return () => socket.off('pesajes_updated', handler);
  }, []);

  const toggle = (key) => setExpanded(prev => ({ ...prev, [key]: !prev[key] }));
  const setAll = (val) => {
    const all = {};
    resumen.grupos.forEach(g => { all[`${g.molde}|${g.color}`] = val; });
    setExpanded(all);
  };

  const formatTime = (iso) => {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' });
  };

  if (loading) return <div className="avance-loading">Cargando avance...</div>;
  if (error) return <div className="avance-error">{error}</div>;
  if (!resumen || !resumen.grupos || resumen.grupos.length === 0) {
    return (
      <div className="avance-empty">
        <h3>📊 No hay pesajes registrados hoy</h3>
        <p>Los datos aparecerán aquí cuando comiences a pesar.</p>
      </div>
    );
  }

  const renderTree = () => (
    <div className="avance-tree">
      {resumen.grupos.map((group) => {
        const key = `${group.molde}|${group.color}`;
        const isOpen = expanded[key];

        return (
          <div key={key} className={`color-group ${isOpen ? 'open' : ''}`}>
            <div className="color-header" onClick={() => toggle(key)}>
              <div className="color-left">
                <span className="expand-icon">{isOpen ? '▼' : '▶'}</span>
                <ColorDot color={group.color} />
                <span className="group-name">
                  <span className="molde-name">{group.molde}</span>
                  <span className="color-tag">{group.color}</span>
                </span>
              </div>
              <div className="color-stats">
                <span className="stat-kg">{group.total_kg.toFixed(1)} kg</span>
                <span className="stat-bolsas">{group.total_bolsas} bolsa{group.total_bolsas !== 1 ? 's' : ''}</span>
              </div>
            </div>

            {isOpen && (
              <div className="color-body">
                <div className="bolsas-list">
                  {group.pesajes.map((p, i) => (
                    <div key={p.id} className="bolsa-row">
                      <span className="bolsa-num">#{group.pesajes.length - i}</span>
                      <span className="bolsa-time">{formatTime(p.fecha_hora)}</span>
                      <span className="bolsa-ot">OT {p.nro_orden_trabajo || '—'}</span>
                      <span className="bolsa-peso">{p.peso_kg?.toFixed(1)} kg</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );

  // ═══ BIG MODE ═══
  if (bigMode) {
    return (
      <div className="avance-container big-mode">
        <div className="avance-header">
          <h2>📊 AVANCE EN VIVO</h2>
          <div className="header-actions">
            <span className="total-global">
              <strong>{resumen.total_global_kg.toFixed(1)} kg</strong> — {resumen.total_registros} bolsas
            </span>
            <button className="btn btn-secondary" onClick={() => setAll(true)}>Expandir</button>
            <button className="btn btn-secondary" onClick={() => setAll(false)}>Colapsar</button>
            <button className="btn btn-secondary" onClick={() => setBigMode(false)}>✕ Cerrar</button>
          </div>
        </div>
        {renderTree()}
      </div>
    );
  }

  // ═══ STANDARD ═══
  return (
    <div className="avance-container">
      <div className="avance-header">
        <h2>📊 Avance ({resumen.fecha})</h2>
        <div className="header-actions">
          <span className="total-global">
            Total: <strong>{resumen.total_global_kg.toFixed(1)} kg</strong> ({resumen.total_registros} bolsas)
          </span>
          <button className="btn btn-secondary btn-sm" onClick={() => setAll(true)}>Expandir</button>
          <button className="btn btn-secondary btn-sm" onClick={() => setAll(false)}>Colapsar</button>
          <button className="btn btn-primary" onClick={() => setBigMode(true)}>📺 Pantalla Grande</button>
        </div>
      </div>
      {renderTree()}
    </div>
  );
}

export default AvanceDashboard;
