import React, { useState, useEffect } from 'react';
import { pesajesApi } from '../services/api';
import './GestionPesajes.css';

function GestionPesajes() {
  const [pesajes, setPesajes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({
    nro_op: '',
    molde: '',
    nro_ot: '',
    fecha_inicio: '',
    fecha_fin: ''
  });
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [selected, setSelected] = useState(new Set());
  const [toast, setToast] = useState(null);
  
  // Custom modal state for confirmations
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  const showToast = (message, type = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const buscar = async (page = 1) => {
    setLoading(true);
    try {
      const { data } = await pesajesApi.buscar({ ...filters, page, per_page: 30 });
      setPesajes(data.items || []);
      setPagination({ page: data.page, pages: data.pages, total: data.total });
      setSelected(new Set());
    } catch (err) {
      console.error('Error buscando pesajes:', err);
      showToast('❌ Error al buscar', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    buscar();
  }, []);

  const handleFilterChange = (e) => {
    const { name, value } = e.target;
    setFilters(prev => ({ ...prev, [name]: value }));
  };

  const handleBuscar = (e) => {
    e.preventDefault();
    buscar(1);
  };

  const handleLimpiar = () => {
    setFilters({ nro_op: '', molde: '', nro_ot: '', fecha_inicio: '', fecha_fin: '' });
  };

  const toggleSelect = (id) => {
    setSelected(prev => {
      const newSet = new Set(prev);
      if (newSet.has(id)) {
        newSet.delete(id);
      } else {
        newSet.add(id);
      }
      return newSet;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === pesajes.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(pesajes.map(p => p.id)));
    }
  };

  const handleEliminarSeleccionados = () => {
    if (selected.size === 0) return;
    setDeleteConfirm({
      type: 'bulk',
      count: selected.size,
      ids: Array.from(selected)
    });
  };

  const handleEliminarUno = (id) => {
    setDeleteConfirm({
      type: 'single',
      id: id
    });
  };

  const executeDelete = async () => {
    if (!deleteConfirm) return;
    
    try {
      if (deleteConfirm.type === 'bulk') {
        await pesajesApi.eliminarBulk(deleteConfirm.ids);
        showToast(`🗑️ ${deleteConfirm.count} pesaje(s) eliminado(s)`);
      } else if (deleteConfirm.type === 'single') {
        await pesajesApi.eliminar(deleteConfirm.id);
        showToast('🗑️ Pesaje eliminado');
      }
      
      setDeleteConfirm(null);
      buscar(pagination.page);
    } catch (err) {
      showToast('❌ Error al eliminar', 'error');
      setDeleteConfirm(null);
    }
  };

  const cancelDelete = () => {
    setDeleteConfirm(null);
  };

  const formatDate = (isoDate) => {
    if (!isoDate) return '—';
    const date = new Date(isoDate);
    return date.toLocaleString('es-PE', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  };

  return (
    <div className="gestion-container">
      {/* Modal Personalizado para Confirmación */}
      {deleteConfirm && (
        <div className="custom-modal-overlay">
          <div className="custom-modal">
            <h3>⚠️ Confirmar Eliminación</h3>
            {deleteConfirm.type === 'bulk' ? (
              <p>¿Eliminar {deleteConfirm.count} pesaje(s) seleccionado(s)? Esta acción no se puede deshacer.</p>
            ) : (
              <p>¿Eliminar este pesaje? Esta acción no se puede deshacer.</p>
            )}
            <div className="custom-modal-actions">
              <button className="btn btn-secondary" onClick={cancelDelete}>Cancelar</button>
              <button className="btn btn-danger" onClick={executeDelete}>Sí, Eliminar</button>
            </div>
          </div>
        </div>
      )}

      <div className="gestion-header">
        <h2>📦 Gestión de Pesajes</h2>
        <span className="gestion-subtitle">Buscar y eliminar pesajes antiguos</span>
      </div>

      {/* Filtros */}
      <form className="gestion-filters" onSubmit={handleBuscar}>
        <div className="filter-field">
          <label>N° OP</label>
          <input
            type="text"
            name="nro_op"
            value={filters.nro_op}
            onChange={handleFilterChange}
            placeholder="Ej: OP1354"
          />
        </div>
        <div className="filter-field">
          <label>Molde</label>
          <input
            type="text"
            name="molde"
            value={filters.molde}
            onChange={handleFilterChange}
            placeholder="Ej: CERNIDOR"
          />
        </div>
        <div className="filter-field">
          <label>N° OT</label>
          <input
            type="text"
            name="nro_ot"
            value={filters.nro_ot}
            onChange={handleFilterChange}
            placeholder="Ej: 054231"
          />
        </div>
        <div className="filter-field">
          <label>Desde</label>
          <input
            type="date"
            name="fecha_inicio"
            value={filters.fecha_inicio}
            onChange={handleFilterChange}
          />
        </div>
        <div className="filter-field">
          <label>Hasta</label>
          <input
            type="date"
            name="fecha_fin"
            value={filters.fecha_fin}
            onChange={handleFilterChange}
          />
        </div>
        <div className="filter-actions">
          <button type="submit" className="btn btn-primary">🔍 Buscar</button>
          <button type="button" className="btn btn-secondary" onClick={handleLimpiar}>🔄 Limpiar</button>
        </div>
      </form>

      {/* Acciones masivas */}
      <div className="gestion-toolbar">
        <span className="results-count">
          {pagination.total} resultado{pagination.total !== 1 ? 's' : ''}
        </span>
        {selected.size > 0 && (
          <button className="btn btn-danger" onClick={handleEliminarSeleccionados}>
            🗑️ Eliminar {selected.size} seleccionado{selected.size !== 1 ? 's' : ''}
          </button>
        )}
      </div>

      {/* Tabla */}
      <div className="gestion-table-wrap">
        <table className="gestion-table">
          <thead>
            <tr>
              <th className="col-check">
                <input
                  type="checkbox"
                  checked={pesajes.length > 0 && selected.size === pesajes.length}
                  onChange={toggleSelectAll}
                />
              </th>
              <th>ID</th>
              <th>Fecha</th>
              <th>Peso (kg)</th>
              <th>N° OP</th>
              <th>Molde</th>
              <th>N° OT</th>
              <th>Color</th>
              <th>Operador</th>
              <th className="col-actions">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="10" className="td-center">Buscando...</td></tr>
            ) : pesajes.length === 0 ? (
              <tr><td colSpan="10" className="td-center">No se encontraron pesajes</td></tr>
            ) : pesajes.map(p => (
              <tr key={p.id} className={selected.has(p.id) ? 'selected' : ''}>
                <td className="col-check">
                  <input
                    type="checkbox"
                    checked={selected.has(p.id)}
                    onChange={() => toggleSelect(p.id)}
                  />
                </td>
                <td className="td-id">{p.id}</td>
                <td className="td-date">{formatDate(p.fecha_hora)}</td>
                <td className="td-peso">{p.peso_kg?.toFixed(1)}</td>
                <td>{p.nro_op || '—'}</td>
                <td>{p.molde || '—'}</td>
                <td>{p.nro_orden_trabajo || '—'}</td>
                <td>{p.color || '—'}</td>
                <td>{p.operador || '—'}</td>
                <td className="col-actions">
                  <button
                    className="btn btn-icon btn-danger"
                    onClick={() => handleEliminarUno(p.id)}
                    title="Eliminar"
                  >
                    🗑️
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Paginación */}
      {pagination.pages > 1 && (
        <div className="gestion-pagination">
          <button
            className="btn btn-secondary btn-sm"
            disabled={pagination.page <= 1}
            onClick={() => buscar(pagination.page - 1)}
          >
            ← Anterior
          </button>
          <span className="page-info">
            Página {pagination.page} de {pagination.pages}
          </span>
          <button
            className="btn btn-secondary btn-sm"
            disabled={pagination.page >= pagination.pages}
            onClick={() => buscar(pagination.page + 1)}
          >
            Siguiente →
          </button>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className={`toast ${toast.type}`}>
          {toast.message}
        </div>
      )}
    </div>
  );
}

export default GestionPesajes;
