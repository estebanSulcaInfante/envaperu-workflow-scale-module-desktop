import React, { useEffect, useState } from 'react';
import { pesajesApi } from '../services/api';
import './GestionPesajes.css';


const CLASSIFICATION_COPY = {
  LOCAL_CAPTURE: 'Captura local',
  LOCAL_ONLY_LEGACY: 'Legacy solo local',
  LEGACY_ACKNOWLEDGED_UNVERIFIABLE: 'Central no verificable',
  LEGACY_VOID_LOCAL: 'Anulado legacy',
};

const REQUEST_STATUS_COPY = {
  PENDING_LOCAL_REVIEW: 'Pendiente local',
  REQUIRES_CENTRAL_REVIEW: 'Revisión central',
};

const CORRECTABLE_FIELDS = [
  'nro_op',
  'molde',
  'maquina',
  'nro_orden_trabajo',
  'color',
  'operador',
  'observaciones',
];

const defaultUuidFactory = () => {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (token) => {
    const random = Math.floor(Math.random() * 16);
    const value = token === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
};

const initialProposedValues = (pesaje) => ({
  peso_kg: Number(pesaje.peso_kg || 0).toFixed(3),
  nro_op: pesaje.nro_op || '',
  molde: pesaje.molde || '',
  maquina: pesaje.maquina || '',
  nro_orden_trabajo: pesaje.nro_orden_trabajo || '',
  color: pesaje.color || '',
  operador: pesaje.operador || '',
  observaciones: pesaje.observaciones || '',
});

const proposedDelta = (draft) => {
  if (draft.action === 'VOID') return {};
  const changes = {};
  const originalWeight = Number(draft.pesaje.peso_kg || 0).toFixed(3);
  const proposedWeight = Number(draft.proposed.peso_kg).toFixed(3);
  if (proposedWeight !== originalWeight) {
    changes.peso_kg = draft.proposed.peso_kg.trim();
  }
  CORRECTABLE_FIELDS.forEach((field) => {
    const original = String(draft.pesaje[field] || '').trim();
    const proposed = String(draft.proposed[field] || '').trim();
    if (original !== proposed) changes[field] = proposed || null;
  });
  return changes;
};

function GestionPesajes({ uuidFactory = defaultUuidFactory }) {
  const [pesajes, setPesajes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({
    id: '',
    nro_op: '',
    molde: '',
    nro_ot: '',
    fecha_inicio: '',
    fecha_fin: '',
  });
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [toast, setToast] = useState(null);
  const [correctionDraft, setCorrectionDraft] = useState(null);
  const [submittingCorrection, setSubmittingCorrection] = useState(false);

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
    } catch (err) {
      console.error('Error buscando pesajes:', err);
      showToast('Error al buscar', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    buscar();
  }, []);

  const handleFilterChange = (event) => {
    const { name, value } = event.target;
    setFilters((previous) => ({ ...previous, [name]: value }));
  };

  const handleBuscar = (event) => {
    event.preventDefault();
    buscar(1);
  };

  const handleLimpiar = () => {
    setFilters({
      id: '',
      nro_op: '',
      molde: '',
      nro_ot: '',
      fecha_inicio: '',
      fecha_fin: '',
    });
  };

  const handleImprimir = async (id) => {
    try {
      const { data } = await pesajesApi.imprimir(id);
      if (data.status === 'SAVED_PRINTED') {
        showToast('Sticker enviado a imprimir');
      } else {
        showToast('Pesaje guardado; impresion fallida', 'error');
      }
    } catch (err) {
      console.error('Error al imprimir:', err);
      showToast('No se pudo confirmar la impresion', 'error');
    }
  };

  const openCorrection = (pesaje) => {
    setCorrectionDraft({
      requestId: uuidFactory(),
      pesaje,
      action: 'CORRECT',
      requestedBy: '',
      reason: '',
      evidenceReference: '',
      proposed: initialProposedValues(pesaje),
    });
  };

  const updateCorrectionField = (field, value) => {
    setCorrectionDraft((previous) => ({ ...previous, [field]: value }));
  };

  const updateProposedField = (field, value) => {
    setCorrectionDraft((previous) => ({
      ...previous,
      proposed: { ...previous.proposed, [field]: value },
    }));
  };

  const submitCorrection = async (event) => {
    event.preventDefault();
    if (submittingCorrection || !correctionDraft) return;
    const changes = proposedDelta(correctionDraft);
    if (!correctionDraft.requestedBy.trim()) {
      showToast('Solicitado por es requerido', 'error');
      return;
    }
    if (!correctionDraft.reason.trim()) {
      showToast('El motivo es requerido', 'error');
      return;
    }
    if (correctionDraft.action === 'CORRECT') {
      const proposedWeight = Number(correctionDraft.proposed.peso_kg);
      if (!Number.isFinite(proposedWeight) || proposedWeight <= 0) {
        showToast('El peso propuesto debe ser mayor que cero', 'error');
        return;
      }
    }
    if (
      correctionDraft.action === 'CORRECT'
      && Object.keys(changes).length === 0
    ) {
      showToast('Modifique al menos un valor', 'error');
      return;
    }

    setSubmittingCorrection(true);
    try {
      const payload = {
        action: correctionDraft.action,
        requested_by: correctionDraft.requestedBy.trim(),
        reason: correctionDraft.reason.trim(),
        evidence_reference: correctionDraft.evidenceReference.trim() || null,
        proposed_changes: changes,
      };
      const { data } = await pesajesApi.solicitarCorreccion(
        correctionDraft.pesaje.id,
        payload,
        correctionDraft.requestId,
      );
      const needsCentral = (
        data.correction_request.status === 'REQUIRES_CENTRAL_REVIEW'
      );
      showToast(
        needsCentral
          ? 'Solicitud registrada para revisión central; el original se conserva.'
          : 'Solicitud registrada; el pesaje original se conserva.',
      );
      setCorrectionDraft(null);
      await buscar(pagination.page);
    } catch (err) {
      const code = err.response?.data?.code;
      showToast(
        code === 'IDEMPOTENCY_CONFLICT'
          ? 'Conflicto de solicitud; requiere revisión.'
          : 'No se confirmó la solicitud. Reintentar conserva el mismo ID.',
        'error',
      );
    } finally {
      setSubmittingCorrection(false);
    }
  };

  const formatDate = (isoDate) => {
    if (!isoDate) return '-';
    const parsed = new Date(isoDate);
    return parsed.toLocaleString('es-PE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="gestion-container">
      {correctionDraft && (
        <div className="custom-modal-overlay">
          <form
            className="custom-modal correction-modal"
            onSubmit={submitCorrection}
            role="dialog"
            aria-modal="true"
            aria-labelledby="correction-modal-title"
          >
            <h3 id="correction-modal-title">Solicitar corrección</h3>
            <p>
              Pesaje #{correctionDraft.pesaje.id}. La solicitud conserva el
              registro original y queda pendiente de revisión.
            </p>

            <div className="correction-mode" role="group" aria-label="Tipo de solicitud">
              <button
                type="button"
                className={correctionDraft.action === 'CORRECT' ? 'active' : ''}
                aria-pressed={correctionDraft.action === 'CORRECT'}
                onClick={() => updateCorrectionField('action', 'CORRECT')}
              >
                Corregir datos
              </button>
              <button
                type="button"
                className={correctionDraft.action === 'VOID' ? 'active' : ''}
                aria-pressed={correctionDraft.action === 'VOID'}
                onClick={() => updateCorrectionField('action', 'VOID')}
              >
                Solicitar anulación
              </button>
            </div>

            {correctionDraft.action === 'CORRECT' && (
              <div className="correction-fields">
                <label>
                  Peso propuesto (kg)
                  <input
                    type="number"
                    min="0.001"
                    step="0.001"
                    value={correctionDraft.proposed.peso_kg}
                    onChange={(event) => updateProposedField('peso_kg', event.target.value)}
                  />
                </label>
                <label>
                  N° OP propuesto
                  <input
                    type="text"
                    value={correctionDraft.proposed.nro_op}
                    onChange={(event) => updateProposedField('nro_op', event.target.value)}
                  />
                </label>
                <label>
                  Molde propuesto
                  <input
                    type="text"
                    value={correctionDraft.proposed.molde}
                    onChange={(event) => updateProposedField('molde', event.target.value)}
                  />
                </label>
                <label>
                  Máquina propuesta
                  <input
                    type="text"
                    value={correctionDraft.proposed.maquina}
                    onChange={(event) => updateProposedField('maquina', event.target.value)}
                  />
                </label>
                <label>
                  N° OT propuesto
                  <input
                    type="text"
                    value={correctionDraft.proposed.nro_orden_trabajo}
                    onChange={(event) => updateProposedField('nro_orden_trabajo', event.target.value)}
                  />
                </label>
                <label>
                  Color de pieza propuesto
                  <input
                    type="text"
                    value={correctionDraft.proposed.color}
                    onChange={(event) => updateProposedField('color', event.target.value)}
                  />
                </label>
                <label>
                  Operador propuesto
                  <input
                    type="text"
                    value={correctionDraft.proposed.operador}
                    onChange={(event) => updateProposedField('operador', event.target.value)}
                  />
                </label>
                <label className="correction-wide-field">
                  Observaciones propuestas
                  <textarea
                    value={correctionDraft.proposed.observaciones}
                    onChange={(event) => updateProposedField('observaciones', event.target.value)}
                  />
                </label>
              </div>
            )}

            <div className="correction-audit-fields">
              <label>
                Solicitado por
                <input
                  type="text"
                  maxLength="100"
                  value={correctionDraft.requestedBy}
                  onChange={(event) => updateCorrectionField('requestedBy', event.target.value)}
                  required
                />
              </label>
              <label>
                Evidencia / referencia
                <input
                  type="text"
                  maxLength="500"
                  value={correctionDraft.evidenceReference}
                  onChange={(event) => updateCorrectionField('evidenceReference', event.target.value)}
                />
              </label>
              <label className="correction-wide-field">
                Motivo
                <textarea
                  maxLength="500"
                  value={correctionDraft.reason}
                  onChange={(event) => updateCorrectionField('reason', event.target.value)}
                  required
                />
              </label>
            </div>

            <div className="custom-modal-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setCorrectionDraft(null)}
                disabled={submittingCorrection}
              >
                Cancelar
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={submittingCorrection}
              >
                {submittingCorrection ? 'Registrando...' : 'Registrar solicitud'}
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="gestion-header">
        <h2>Gestión de pesajes</h2>
        <span className="gestion-subtitle">
          Consulta, reimpresión y solicitudes auditables
        </span>
      </div>

      <form className="gestion-filters" onSubmit={handleBuscar}>
        <div className="filter-field">
          <label>ID</label>
          <input
            type="number"
            name="id"
            value={filters.id}
            onChange={handleFilterChange}
            placeholder="Ej: 154"
          />
        </div>
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
          <button type="submit" className="btn btn-primary">Buscar</button>
          <button type="button" className="btn btn-secondary" onClick={handleLimpiar}>
            Limpiar
          </button>
        </div>
      </form>

      <div className="gestion-toolbar">
        <span className="results-count">
          {pagination.total} resultado{pagination.total !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="gestion-table-wrap">
        <table className="gestion-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Fecha</th>
              <th>Peso (kg)</th>
              <th>N° OP</th>
              <th>Molde</th>
              <th>N° OT</th>
              <th>Color de pieza</th>
              <th>Operador</th>
              <th>Trazabilidad</th>
              <th>Solicitud</th>
              <th className="col-actions">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="11" className="td-center">Buscando...</td></tr>
            ) : pesajes.length === 0 ? (
              <tr><td colSpan="11" className="td-center">No se encontraron pesajes</td></tr>
            ) : pesajes.map((pesaje) => (
              <tr key={pesaje.id}>
                <td className="td-id">{pesaje.id}</td>
                <td className="td-date">{formatDate(pesaje.fecha_hora)}</td>
                <td className="td-peso">{pesaje.peso_kg?.toFixed(3)}</td>
                <td>{pesaje.nro_op || '-'}</td>
                <td>{pesaje.molde || '-'}</td>
                <td>{pesaje.nro_orden_trabajo || '-'}</td>
                <td>{pesaje.color || '-'}</td>
                <td>{pesaje.operador || '-'}</td>
                <td>
                  <span className={`traceability-badge ${pesaje.traceability_classification?.toLowerCase()}`}>
                    {CLASSIFICATION_COPY[pesaje.traceability_classification] || 'Sin clasificar'}
                  </span>
                </td>
                <td>
                  <span className="request-status">
                    {REQUEST_STATUS_COPY[pesaje.latest_correction_request?.status] || 'Sin solicitudes'}
                  </span>
                </td>
                <td className="col-actions">
                  <button
                    className="btn btn-icon btn-secondary"
                    onClick={() => handleImprimir(pesaje.id)}
                    title="Imprimir sticker"
                    aria-label={`Imprimir sticker del pesaje #${pesaje.id}`}
                  >
                    <span aria-hidden="true">⎙</span>
                  </button>
                  <button
                    className="btn btn-icon correction-action"
                    onClick={() => openCorrection(pesaje)}
                    title="Solicitar corrección"
                    aria-label={`Solicitar corrección del pesaje #${pesaje.id}`}
                  >
                    <span aria-hidden="true">✎</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pagination.pages > 1 && (
        <div className="gestion-pagination">
          <button
            className="btn btn-secondary btn-sm"
            disabled={pagination.page <= 1}
            onClick={() => buscar(pagination.page - 1)}
          >
            Anterior
          </button>
          <span className="page-info">
            Página {pagination.page} de {pagination.pages}
          </span>
          <button
            className="btn btn-secondary btn-sm"
            disabled={pagination.page >= pagination.pages}
            onClick={() => buscar(pagination.page + 1)}
          >
            Siguiente
          </button>
        </div>
      )}

      {toast && (
        <div className={`toast ${toast.type}`}>
          {toast.message}
        </div>
      )}
    </div>
  );
}

export default GestionPesajes;
