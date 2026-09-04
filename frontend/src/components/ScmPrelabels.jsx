import {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import { scmPrelabelsApi } from '../services/api';

const statusLabel = (job) => {
  const status = String(job?.status || job?.estado || '').toUpperCase();
  if (['PENDING', 'GENERADO', 'GENERADA'].includes(status)) return 'Pendiente de impresión';
  if (['PARTIAL', 'PARCIAL'].includes(status)) return 'Impresión parcial';
  if (['PRINTED', 'IMPRESA'].includes(status)) return 'Impreso';
  if (['FAILED', 'FALLIDA', 'FALLIDA_SIN_EMISION'].includes(status)) return 'Impresión fallida';
  return 'Estado por confirmar';
};

const jobStatus = (job) => String(job?.status || job?.estado || '').toUpperCase();
const isPrintedJob = (job) => Boolean(job?.uiPrintAccepted)
  || ['PRINTED', 'PROCESADO', 'IMPRESA'].includes(jobStatus(job));
const labelStatus = (label) => String(label?.estado || label?.status || '').toUpperCase();
const hasUncertainEmission = (job) => (job?.labels || []).some(
  (label) => labelStatus(label) === 'EMISION_INCIERTA',
);
const hasMixedEmission = (job) => {
  const states = new Set((job?.labels || []).map(labelStatus).filter(Boolean));
  const emitted = [...states].some((state) => ['IMPRESA', 'EMISION_INCIERTA'].includes(state));
  const pending = [...states].some(
    (state) => ['GENERADA', 'FALLIDA_SIN_EMISION'].includes(state),
  );
  return emitted && pending;
};
const requiresReplacement = (job) => hasUncertainEmission(job) || hasMixedEmission(job);
const isRetryWithoutEmission = (job) => {
  const labels = job?.labels || [];
  return labels.length > 0 && labels.every(
    (label) => labelStatus(label) === 'FALLIDA_SIN_EMISION',
  );
};

const jobMangas = (job) => (job?.labels || [])
  .map((label) => label.manga_codigo || label.payload?.codigo_manga)
  .filter(Boolean)
  .join(', ');

const firstPayload = (job) => job?.labels?.[0]?.payload || {};

const jobContext = (job) => {
  const payload = firstPayload(job);
  const piece = payload.pieza_color
    || payload.articulo_nombre
    || payload.nombre_articulo
    || payload.articulo?.nombre
    || payload.articulo?.descripcion
    || '';
  const color = payload.color || payload.color_nombre || payload.nombre_color || '';
  const order = payload.of_ot || payload.oa_ot || payload.op_ot || '';
  const quantity = payload.cantidad_planificada_un || payload.cantidad_confirmada_un || '';
  const operator = payload.maquinista || payload.responsable || '';
  const mangas = jobMangas(job);
  const title = [piece, color].filter(Boolean).join(' · ') || mangas || 'Trabajo sin descripción';
  let createdTime = '';
  if (job?.created_at) {
    const createdAt = new Date(job.created_at);
    if (!Number.isNaN(createdAt.getTime())) {
      createdTime = new Intl.DateTimeFormat('es-PE', {
        hour: '2-digit',
        minute: '2-digit',
      }).format(createdAt);
    }
  }
  return {
    title,
    piece,
    color,
    order,
    quantity,
    operator,
    mangas,
    createdTime,
  };
};

const normalizeSearch = (value) => String(value || '')
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .toLowerCase();

const jobMatches = (job, query) => {
  const terms = normalizeSearch(query).split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const context = jobContext(job);
  const haystack = normalizeSearch([
    context.title,
    context.order,
    context.mangas,
    context.quantity,
    context.operator,
    job?.print_job_id,
  ].join(' '));
  return terms.every((term) => haystack.includes(term));
};

export default function ScmPrelabels({ initialJobId = '' }) {
  const [jobId, setJobId] = useState(String(initialJobId || '').trim());
  const [job, setJob] = useState(null);
  const [previewSvg, setPreviewSvg] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);
  const [pendingJobs, setPendingJobs] = useState([]);
  const [pendingLoading, setPendingLoading] = useState(true);
  const [pendingUnavailable, setPendingUnavailable] = useState(false);
  const [filterQuery, setFilterQuery] = useState('');
  const [selectedJobId, setSelectedJobId] = useState('');
  const [activeAction, setActiveAction] = useState('');
  const [technicalSearchOpen, setTechnicalSearchOpen] = useState(false);
  const initialPreviewStarted = useRef(false);

  const loadPending = useCallback(async () => {
    setPendingLoading(true);
    setPendingUnavailable(false);
    try {
      const { data } = await scmPrelabelsApi.pending({ status: 'PENDING', limit: 20 });
      setPendingJobs(Array.isArray(data.print_jobs) ? data.print_jobs : []);
    } catch (error) {
      setPendingJobs([]);
      setPendingUnavailable(true);
      setTechnicalSearchOpen(true);
      if (![404, 501].includes(error.response?.status)) {
        setMessage({
          type: 'error',
          text: 'No se pudo actualizar la bandeja. La búsqueda manual sigue disponible.',
        });
      }
    } finally {
      setPendingLoading(false);
    }
  }, []);

  const requestJob = useCallback(async (action, requestedJobId) => {
    const normalizedJobId = String(requestedJobId || '').trim();
    if (!normalizedJobId) return;
    setJobId(normalizedJobId);
    setSelectedJobId(normalizedJobId);
    setLoading(true);
    setActiveAction(action);
    setMessage(null);
    if (action === 'preview') {
      setJob(null);
      setPreviewSvg('');
    }
    try {
      const { data } = await scmPrelabelsApi[action](normalizedJobId);
      const requestedJob = action === 'print' && data.result === 'IMPRESA'
        ? { ...data.print_job, uiPrintAccepted: true }
        : data.print_job;
      setJob(requestedJob);
      if (data.preview_svg) setPreviewSvg(data.preview_svg);
      else if (action === 'preview') setPreviewSvg('');
      if (action === 'preview') {
        if (requiresReplacement(requestedJob)) {
          setMessage({
            type: 'error',
            text: 'No reimprima este trabajo: existe una emisión incierta o parcial. Invalide el sticker afectado y genere una etiqueta de reemplazo desde la OT.',
          });
        } else if (isPrintedJob(requestedJob)) {
          setMessage({
            type: 'success',
            text: 'Trabajo recibido por la estación. Estos stickers ya fueron impresos; la vista previa no los reimprime.',
          });
        } else {
          setMessage({
            type: 'info',
            text: 'Trabajo recibido por la estación y pendiente de impresión. Previsualizar no envía stickers a la impresora.',
          });
        }
      } else {
        setMessage({
          type: data.result === 'IMPRESA' ? 'success' : 'error',
          text: data.result === 'IMPRESA'
            ? 'Trabajo enviado y acuse técnico registrado. Verifique que salieron todas las hojas.'
            : `Resultado técnico: ${data.result}. Revise la recuperación indicada antes de reintentar.`,
        });
        await loadPending();
      }
    } catch (error) {
      if (action === 'preview') {
        setJob(null);
        setPreviewSvg('');
      }
      setMessage({
        type: 'error',
        text: error.response?.data?.message || 'No se pudo abrir el trabajo central.',
      });
    } finally {
      setLoading(false);
      setActiveAction('');
    }
  }, [loadPending]);

  useEffect(() => {
    loadPending();
  }, [loadPending]);

  useEffect(() => {
    const requestedJobId = String(initialJobId || '').trim();
    if (!requestedJobId || initialPreviewStarted.current) return;
    initialPreviewStarted.current = true;
    requestJob('preview', requestedJobId);
  }, [initialJobId, requestJob]);

  const previewSrc = useMemo(
    () => previewSvg
      ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(previewSvg)}`
      : '',
    [previewSvg],
  );

  const filteredPendingJobs = useMemo(
    () => pendingJobs.filter((pendingJob) => jobMatches(pendingJob, filterQuery)),
    [filterQuery, pendingJobs],
  );

  const selectedContext = useMemo(() => jobContext(job), [job]);

  return (
    <div className="panel">
      <div className="panel-header">ETIQUETAS SCM · VISTA PREVIA E IMPRESIÓN</div>
      <div className="panel-body">
        <p className="scm-help">
          Previsualizar es una consulta: no imprime ni cambia el estado de las etiquetas.
          Solo «Imprimir sticker» envía el trabajo a la impresora.
        </p>
        <div className="scm-print-workspace">
          <section className="scm-pending-section" aria-labelledby="scm-pending-title">
            <div className="scm-section-heading">
              <div>
                <h2 id="scm-pending-title">Pendientes de impresión</h2>
                <p>Elija por pieza, color y OF/OT; el código técnico es secundario.</p>
              </div>
              <button
                className="btn btn-secondary btn-sm"
                type="button"
                disabled={pendingLoading || loading}
                onClick={loadPending}
              >
                {pendingLoading ? 'Actualizando…' : 'Actualizar'}
              </button>
            </div>

            <div className="scm-pending-filter">
              <label htmlFor="scm-pending-filter">
                Buscar por pieza, color, OF/OT, manga o maquinista
              </label>
              <input
                id="scm-pending-filter"
                type="search"
                value={filterQuery}
                onChange={(event) => setFilterQuery(event.target.value)}
                placeholder="Ej.: florero blanco u OF-000014"
                autoComplete="off"
                aria-describedby="scm-filter-scope"
              />
              <small id="scm-filter-scope">
                Busca dentro de los {pendingJobs.length} trabajos cargados en esta estación.
              </small>
            </div>

            {pendingLoading && (
              <p className="scm-empty-state" role="status">Cargando trabajos…</p>
            )}
            {pendingUnavailable && (
              <div className="scm-message info" role="status">
                La bandeja no está disponible en esta versión; la búsqueda manual sigue disponible.
              </div>
            )}
            {!pendingLoading && !pendingUnavailable && pendingJobs.length === 0 && (
              <p className="scm-empty-state">No hay trabajos pendientes para esta estación.</p>
            )}
            {!pendingLoading && pendingJobs.length > 0 && filteredPendingJobs.length === 0 && (
              <p className="scm-empty-state">
                Ningún trabajo cargado coincide. Limpie la búsqueda o actualice la bandeja.
              </p>
            )}
            {filteredPendingJobs.length > 0 && (
              <ul className="scm-pending-list" aria-label="Trabajos de impresión cargados">
                {filteredPendingJobs.map((pendingJob) => {
                  const context = jobContext(pendingJob);
                  const isSelected = selectedJobId === pendingJob.print_job_id;
                  return (
                    <li
                      key={pendingJob.print_job_id}
                      className={isSelected ? 'selected' : ''}
                    >
                      <button
                        className="scm-pending-job"
                        type="button"
                        disabled={loading}
                        aria-pressed={isSelected}
                        aria-label={`Seleccionar ${context.title}${context.order ? `, ${context.order}` : ''}`}
                        onClick={() => requestJob('preview', pendingJob.print_job_id)}
                      >
                        <span className="scm-job-card-heading">
                          <strong>{context.title}</strong>
                          <span>{statusLabel(pendingJob)}</span>
                        </span>
                        {context.order && <b>{context.order}</b>}
                        <small>
                          {context.mangas || `${pendingJob.labels?.length || 0} etiqueta(s)`}
                        </small>
                        {(context.quantity || context.operator || context.createdTime) && (
                          <small>
                            {[
                              context.quantity ? `${context.quantity} un.` : '',
                              context.operator,
                              context.createdTime,
                            ].filter(Boolean).join(' · ')}
                          </small>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}

            <details
              className="scm-manual-search"
              open={technicalSearchOpen}
              onToggle={(event) => setTechnicalSearchOpen(event.currentTarget.open)}
            >
              <summary>Búsqueda por ID técnico</summary>
              <p>Respaldo para soporte si el trabajo no aparece en la bandeja.</p>
              <div className="scm-job-search">
                <label htmlFor="scm-print-job-id">ID del trabajo de impresión</label>
                <div>
                  <input
                    id="scm-print-job-id"
                    value={jobId}
                    onChange={(event) => setJobId(event.target.value)}
                    placeholder="UUID del trabajo de impresión"
                    autoComplete="off"
                  />
                  <button
                    className="btn btn-secondary"
                    type="button"
                    disabled={loading || !jobId.trim()}
                    onClick={() => requestJob('preview', jobId)}
                  >
                    {activeAction === 'preview' ? 'Consultando…' : 'Previsualizar'}
                  </button>
                </div>
              </div>
            </details>
          </section>

          <section
            className="scm-preview-section scm-selected-job"
            aria-label="Trabajo seleccionado"
            aria-busy={activeAction === 'preview'}
          >
            <div className="scm-section-heading">
              <div>
                <h2 id="scm-preview-title">Trabajo seleccionado</h2>
                <p>Revise el contenido antes de enviar stickers a la impresora.</p>
              </div>
              {job && <span className="scm-selected-status">{statusLabel(job)}</span>}
            </div>

            {message && (
              <div className={`scm-message ${message.type}`} role="status" aria-live="polite">
                {message.text}
              </div>
            )}

            {activeAction === 'preview' && !job && (
              <div className="scm-selected-empty" role="status">
                <strong>Cargando vista previa…</strong>
                <span>La selección anterior se retiró para evitar imprimir otro trabajo.</span>
              </div>
            )}

            {!job && activeAction !== 'preview' && (
              <div className="scm-selected-empty">
                <strong>Seleccione un trabajo de la bandeja</strong>
                <span>Aquí aparecerán su descripción, hoja y acción de impresión.</span>
              </div>
            )}

            {job && (
              <>
                <div className="scm-selected-context">
                  <strong>{selectedContext.title}</strong>
                  <span>
                    {[selectedContext.order, selectedContext.mangas].filter(Boolean).join(' · ')}
                  </span>
                  {(selectedContext.quantity || selectedContext.operator) && (
                    <small>
                      {[
                        selectedContext.quantity ? `${selectedContext.quantity} un.` : '',
                        selectedContext.operator,
                      ].filter(Boolean).join(' · ')}
                    </small>
                  )}
                </div>

                {previewSrc ? (
                  <figure className="scm-render-preview">
                    <img src={previewSrc} alt="Simulación física 109 × 50 mm de la hoja TSPL" />
                    <figcaption>
                      Simulación web del layout TSPL · 109 × 50 mm · 203 DPI
                    </figcaption>
                  </figure>
                ) : (
                  <div className="scm-preview-unavailable">
                    Vista previa gráfica no disponible; revise el resumen antes de imprimir.
                  </div>
                )}

                <div className="sr-only" aria-live="polite">
                  {(job.labels || []).map((label) => (
                    <span key={label.public_id}>
                      <span>{label.payload?.codigo_manga || label.manga_codigo}</span>
                      <span>{`QR: ${label.payload?.qr?.label_id || label.public_id}`}</span>
                      <span>2 copias físicas de la misma identidad</span>
                    </span>
                  ))}
                </div>

                <details className="scm-technical-details">
                  <summary>Detalles técnicos</summary>
                  <dl>
                    <div>
                      <dt>ID del trabajo</dt>
                      <dd>{job.print_job_id}</dd>
                    </div>
                    <div>
                      <dt>Plantilla</dt>
                      <dd>{job.plantilla_version || 'Por confirmar'}</dd>
                    </div>
                  </dl>
                </details>

                <div className="scm-print-summary">
                  <span>
                    {job.labels?.length || 0} identidad(es) · 2 copias por identidad
                  </span>
                  <button
                    className="btn btn-primary"
                    type="button"
                    disabled={loading || isPrintedJob(job) || requiresReplacement(job)}
                    onClick={() => requestJob('print', job.print_job_id)}
                  >
                    {activeAction === 'print'
                      ? 'Imprimiendo…'
                      : (job.uiPrintAccepted
                        ? 'Envío registrado'
                        : (isPrintedJob(job)
                          ? 'Sticker ya impreso'
                          : (requiresReplacement(job)
                            ? 'Requiere etiqueta de reemplazo'
                            : (isRetryWithoutEmission(job)
                              ? 'Reintentar impresión'
                              : 'Imprimir sticker'))))}
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
