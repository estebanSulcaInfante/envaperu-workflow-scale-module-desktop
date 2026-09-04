export default function ScmProductionHome({ onNavigate }) {
  return (
    <section className="scm-module-home" aria-labelledby="production-module-title">
      <div className="scm-module-home-heading">
        <span>Módulo SCM</span>
        <h1 id="production-module-title">Producción</h1>
        <p>Elige la tarea que estás realizando. La estación te indicará qué QR corresponde; ningún escaneo ejecuta una operación por sí solo.</p>
      </div>
      <div className="scm-module-task-grid">
        <button type="button" className="scm-module-task" onClick={() => onNavigate('scm-prelabels')}>
          <span className="scm-module-task-step">Antes de producir</span>
          <strong>Preparar etiquetas</strong>
          <small>Consulta la bandeja, previsualiza el trabajo y envía los stickers a la impresora local.</small>
          <span className="scm-module-task-cta">Abrir etiquetas →</span>
        </button>
        <button type="button" className="scm-module-task" onClick={() => onNavigate('scm-weighing')}>
          <span className="scm-module-task-step">Al cerrar una manga</span>
          <strong>Pesar mangas</strong>
          <small>Escanea una preetiqueta planificada, verifica el contexto y confirma el peso con F2.</small>
          <span className="scm-module-task-cta">Abrir pesaje →</span>
        </button>
      </div>
    </section>
  );
}
