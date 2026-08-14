import {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import { scmPrelabelsApi } from '../services/api';

const statusLabel = (job) => {
  const status = String(job?.status || job?.estado || '').toUpperCase();
  if (['PENDING', 'GENERADO', 'GENERADA'].includes(status)) return 'Pendiente de impresión';
  if (status === 'PARTIAL') return 'Impresión parcial';
  if (['PRINTED', 'IMPRESA'].includes(status)) return 'Impreso';
  if (['FAILED', 'FALLIDA', 'FALLIDA_SIN_EMISION'].includes(status)) return 'Impresión fallida';
  return 'Estado por confirmar';
};

const jobStatus = (job) => String(job?.status || job?.estado || '').toUpperCase();
const isPrintedJob = (job) => ['PRINTED', 'PROCESADO', 'IMPRESA'].includes(jobStatus(job));

const jobMangas = (job) => (job?.labels || [])
  .map((label) => label.manga_codigo || label.payload?.codigo_manga)
  .filter(Boolean)
  .join(', ');

export default function ScmPrelabels({ initialJobId = '' }) {
  const [jobId, setJobId] = useState(String(initialJobId || '').trim());
  const [job, setJob] = useState(null);
  const [previewSvg, setPreviewSvg] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);
  const [pendingJobs, setPendingJobs] = useState([]);
  const [pendingLoading, setPendingLoading] = useState(true);
  const [pendingUnavailable, setPendingUnavailable] = useState(false);
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
    setLoading(true);
    setMessage(null);
    try {
      const { data } = await scmPrelabelsApi[action](normalizedJobId);
      const requestedJob = data.print_job;
      setJob(requestedJob);
      if (data.preview_svg) setPreviewSvg(data.preview_svg);
      else if (action === 'preview') setPreviewSvg('');
      if (action === 'preview') {
        if (isPrintedJob(requestedJob)) {
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
          text: `Resultado: ${data.result}. Acuse central registrado.`,
        });
        await loadPending();
      }
    } catch (error) {
      setMessage({
        type: 'error',
        text: error.response?.data?.message || 'No se pudo abrir el trabajo central.',
      });
    } finally {
      setLoading(false);
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

  return (
    <div className="panel">
      <div className="panel-header">ETIQUETAS SCM · VISTA PREVIA E IMPRESIÓN</div>
      <div className="panel-body">
        <p className="scm-help">
          Previsualizar es una consulta: no imprime ni cambia el estado de las etiquetas.
          Solo «Imprimir sticker» envía el trabajo a la impresora.
        </p>

        <section className="scm-pending-section" aria-labelledby="scm-pending-title">
          <div className="scm-section-heading">
            <div>
              <h2 id="scm-pending-title">Pendientes de impresión</h2>
              <p>Trabajos centrales disponibles para esta estación.</p>
            </div>
            <button
              className="btn btn-secondary btn-sm"
              type="button"
              disabled={pendingLoading}
              onClick={loadPending}
            >
              {pendingLoading ? 'Actualizando…' : 'Actualizar bandeja'}
            </button>
          </div>

          {pendingUnavailable && (
            <div className="scm-message info" role="status">
              La bandeja no está disponible en esta versión; la búsqueda manual sigue disponible.
            </div>
          )}
          {!pendingLoading && !pendingUnavailable && pendingJobs.length === 0 && (
            <p className="scm-empty-state">No hay trabajos pendientes para esta estación.</p>
          )}
          {pendingJobs.length > 0 && (
            <ul className="scm-pending-list">
              {pendingJobs.map((pendingJob) => (
                <li key={pendingJob.print_job_id}>
                  <div>
                    <strong>{jobMangas(pendingJob) || pendingJob.print_job_id}</strong>
                    <span>{statusLabel(pendingJob)}</span>
                    <small>
                      {pendingJob.labels?.length || 0} etiqueta(s) · {pendingJob.print_job_id}
                    </small>
                  </div>
                  <button
                    className="btn btn-secondary btn-sm"
                    type="button"
                    disabled={loading}
                    aria-label={`Previsualizar trabajo ${pendingJob.print_job_id}`}
                    onClick={() => requestJob('preview', pendingJob.print_job_id)}
                  >
                    Ver
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="scm-manual-search" aria-labelledby="scm-manual-title">
          <h2 id="scm-manual-title">Buscar por ID</h2>
          <p>Úsalo como respaldo si el trabajo no aparece en la bandeja.</p>
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
                className="btn btn-primary"
                disabled={loading || !jobId.trim()}
                onClick={() => requestJob('preview', jobId)}
              >
                {loading ? 'Consultando…' : 'Previsualizar'}
              </button>
            </div>
          </div>
        </section>

        {message && (
          <div className={`scm-message ${message.type}`} role="status" aria-live="polite">
            {message.text}
          </div>
        )}
        {job && (
          <section className="scm-preview-section" aria-labelledby="scm-preview-title">
            <div className="scm-section-heading">
              <div>
                <h2 id="scm-preview-title">Vista previa de la hoja</h2>
                <p>{statusLabel(job)} · Trabajo {job.print_job_id}</p>
              </div>
            </div>
            <figure className="scm-render-preview">
              <img src={previewSrc} alt="Simulación física 109 × 50 mm de la hoja TSPL" />
              <figcaption>
                Simulación web del layout TSPL · 109 × 50 mm · 203 DPI
              </figcaption>
            </figure>
            <div className="sr-only" aria-live="polite">
              {(job.labels || []).map((label) => (
                <span key={label.public_id}>
                  <span>{label.payload?.codigo_manga || label.manga_codigo}</span>
                  <span>{`QR: ${label.payload?.qr?.label_id || label.public_id}`}</span>
                </span>
              ))}
              {!job.labels?.[1] && <span>Columna libre</span>}
            </div>
            <div className="scm-print-summary">
              <span>{job.labels?.length || 0} etiqueta(s) · {job.plantilla_version}</span>
              <button
                className="btn btn-primary"
                disabled={loading || isPrintedJob(job)}
                onClick={() => requestJob('print', job.print_job_id)}
              >
                {isPrintedJob(job) ? 'Sticker ya impreso' : 'Imprimir sticker'}
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
