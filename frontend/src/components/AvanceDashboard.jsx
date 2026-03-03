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
  'CARAMELO':     '#AF6E28',
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
  // expanded: { molde: bool } para nivel 1, { "molde|color": bool } para nivel 2
  const [expandedMoldes, setExpandedMoldes] = useState({});
  const [expandedColors, setExpandedColors] = useState({});

  const loadData = async () => {
    try {
      const { data } = await avanceApi.resumen();
      setResumen(data);
      setError(null);
      if (data.grupos_por_molde) {
        setExpandedMoldes(prev => {
          const merged = {};
          data.grupos_por_molde.forEach((m) => {
            merged[m.molde] = prev[m.molde] !== undefined ? prev[m.molde] : true;
          });
          return merged;
        });
        setExpandedColors(prev => {
          const merged = {};
          data.grupos_por_molde.forEach((m) => {
            m.colores.forEach((c) => {
              const key = `${m.molde}|${c.color}`;
              merged[key] = prev[key] !== undefined ? prev[key] : false;
            });
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

  const toggleMolde = (molde) => setExpandedMoldes(prev => ({ ...prev, [molde]: !prev[molde] }));
  const toggleColor = (key) => setExpandedColors(prev => ({ ...prev, [key]: !prev[key] }));

  const setAll = (val) => {
    if (!resumen?.grupos_por_molde) return;
    const moldes = {};
    const colors = {};
    resumen.grupos_por_molde.forEach(m => {
      moldes[m.molde] = val;
      m.colores.forEach(c => { colors[`${m.molde}|${c.color}`] = val; });
    });
    setExpandedMoldes(moldes);
    setExpandedColors(colors);
  };

  const formatTime = (iso) => {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' });
  };

  if (loading) return <div className="avance-loading">Cargando avance...</div>;
  if (error) return <div className="avance-error">{error}</div>;
  if (!resumen || !resumen.grupos_por_molde || resumen.grupos_por_molde.length === 0) {
    return (
      <div className="avance-empty">
        <h3>📊 No hay pesajes registrados hoy</h3>
        <p>Los datos aparecerán aquí cuando comiences a pesar.</p>
      </div>
    );
  }

  const renderTree = () => (
    <div className="avance-tree">
      {resumen.grupos_por_molde.map((moldeGroup) => {
        const isMoldeOpen = expandedMoldes[moldeGroup.molde];

        return (
          <div key={moldeGroup.molde} className={`molde-group ${isMoldeOpen ? 'open' : ''}`}>
            {/* Nivel 1: Header del molde */}
            <div className="molde-header" onClick={() => toggleMolde(moldeGroup.molde)}>
              <div className="molde-left">
                <span className="expand-icon">{isMoldeOpen ? '▼' : '▶'}</span>
                <span className="molde-name">{moldeGroup.molde}</span>
                <span className="molde-colors-count">{moldeGroup.colores.length} color{moldeGroup.colores.length !== 1 ? 'es' : ''}</span>
              </div>
              <div className="molde-stats">
                <span className="stat-kg">{moldeGroup.total_kg.toFixed(1)} kg</span>
                <span className="stat-bolsas">{moldeGroup.total_bolsas} bolsa{moldeGroup.total_bolsas !== 1 ? 's' : ''}</span>
              </div>
            </div>

            {/* Nivel 2: Colores dentro del molde */}
            {isMoldeOpen && (
              <div className="molde-body">
                {moldeGroup.colores.map((colorGroup) => {
                  const colorKey = `${moldeGroup.molde}|${colorGroup.color}`;
                  const isColorOpen = expandedColors[colorKey];

                  return (
                    <div key={colorKey} className={`color-group ${isColorOpen ? 'open' : ''}`}>
                      <div className="color-header" onClick={() => toggleColor(colorKey)}>
                        <div className="color-left">
                          <span className="expand-icon">{isColorOpen ? '▼' : '▶'}</span>
                          <ColorDot color={colorGroup.color} />
                          <span className="color-tag">{colorGroup.color}</span>
                        </div>
                        <div className="color-stats">
                          <span className="stat-kg">{colorGroup.total_kg.toFixed(1)} kg</span>
                          <span className="stat-bolsas">{colorGroup.total_bolsas} bolsa{colorGroup.total_bolsas !== 1 ? 's' : ''}</span>
                        </div>
                      </div>

                      {/* Nivel 3: Pesajes individuales */}
                      {isColorOpen && (
                        <div className="color-body">
                          <div className="bolsas-list">
                            {colorGroup.pesajes.map((p, i) => (
                              <div key={p.id} className="bolsa-row">
                                <span className="bolsa-num">#{colorGroup.pesajes.length - i}</span>
                                <span className="bolsa-time">{formatTime(p.fecha_hora)}</span>
                                <span className="bolsa-ot">OT {p.nro_orden_trabajo || '—'}</span>
                                <span className="bolsa-peso">
                                  {(p.peso_corregido ?? p.peso_kg)?.toFixed(1)} kg
                                  {p.factor_correccion && p.factor_correccion !== 100 && (
                                    <small style={{ color: 'var(--warning)', marginLeft: '4px', fontSize: '0.75em' }}>({p.factor_correccion}%)</small>
                                  )}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
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
        <h2>📊 Avance</h2>
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
