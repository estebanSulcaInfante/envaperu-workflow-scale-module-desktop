import { useRef, useState } from 'react';
import { scmPostReprintsApi } from '../services/api';

export default function ScmPostReprints() {
  const [jobs, setJobs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [results, setResults] = useState({});
  const lock = useRef(false);
  const run = async (action) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try { await action(); }
    catch (error) { setMessage(error.response?.data?.message || 'Sin conexión. Consulte el estado; no solicite otra copia.'); }
    finally { lock.current = false; setBusy(false); }
  };
  const load = () => run(async () => {
    const { data } = await scmPostReprintsApi.list();
    setJobs(data.jobs || []);
    setMessage((data.jobs || []).length ? '' : 'No hay copias pendientes.');
  });
  const print = (id) => run(async () => {
    setResults((current) => ({ ...current, [id]: 'UNCERTAIN' }));
    const { data } = await scmPostReprintsApi.print(id);
    setResults((current) => ({ ...current, [id]: data.result }));
    setMessage(data.result === 'ACCEPTED'
      ? 'Aceptado por el spooler. Recepción física sin confirmar.'
      : 'Emisión no confirmada. Revise la evidencia antes de autorizar otra copia.');
  });
  return <section aria-label="Copias POSTPESAJE" className="scm-post-reprints">
    <h2>Reimpresiones de tickets pesados</h2>
    <p>Copias confirmadas en Central. Conservan el pesaje y la preetiqueta originales.</p>
    <button type="button" className="btn" disabled={busy} onClick={load}>Consultar copias autorizadas</button>{' '}
    <button type="button" className="btn" disabled={busy} onClick={() => run(async () => {
      await scmPostReprintsApi.sync();
      setMessage('Evidencia sincronizada. No se enviaron etiquetas a la impresora.');
    })}>Sincronizar evidencia</button>
    <p role="status">{message}</p>
    {jobs.map((job) => <article key={job.copy_job_id}>
      <strong>{job.payload?.codigo_manga || job.source_label_id}</strong>
      <p>{job.copias} copia(s) · {Math.ceil(job.copias / 2)} soporte(s). El último espacio puede quedar vacío.</p>
      <button type="button" className="btn btn-primary"
        disabled={busy || Boolean(results[job.copy_job_id]) || !['PENDING', 'PENDIENTE'].includes(job.estado || job.state)}
        onClick={() => print(job.copy_job_id)}>
        {results[job.copy_job_id] ? 'Envío registrado; revisar estado' : 'Imprimir copias autorizadas'}
      </button>
    </article>)}
  </section>;
}
