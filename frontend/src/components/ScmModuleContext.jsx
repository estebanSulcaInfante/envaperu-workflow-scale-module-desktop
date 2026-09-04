const MODULE_COPY = {
  production: {
    eyebrow: 'Módulo SCM',
    title: 'Producción',
    description: 'Trabaja con una manga planificada: primero prepara su etiqueta o selecciona el pesaje; después escanea el QR solicitado.',
  },
  preparation: {
    eyebrow: 'Módulo SCM',
    title: 'Preparación de material',
    description: 'Abre una OPM en Central y elige pesar un aporte o una salida. El contexto QR declara la operación antes de leer bolsas de origen.',
  },
  inventory: {
    eyebrow: 'Módulo SCM',
    title: 'Inventario físico',
    description: 'Crea o selecciona una jornada de ingreso en Central. Su contexto QR fija material, ubicación y Calidad antes de capturar una bolsa.',
  },
};

export default function ScmModuleContext({ module, view, onNavigate }) {
  const copy = MODULE_COPY[module];
  if (!copy) return null;

  return (
    <section className="scm-module-context" aria-label={`Módulo ${copy.title}`}>
      <div>
        <span>{copy.eyebrow}</span>
        <h1>{copy.title}{view ? ` · ${view}` : ''}</h1>
        <p>{copy.description}</p>
      </div>
      {module === 'production' && view && (
        <div className="scm-module-context-actions" aria-label="Vistas de Producción">
          <button type="button" className="btn" onClick={() => onNavigate('scm-production')}>
            Inicio de Producción
          </button>
          {view !== 'Etiquetas' && (
            <button type="button" className="btn" onClick={() => onNavigate('scm-prelabels')}>
              Etiquetas
            </button>
          )}
          {view !== 'Pesaje de mangas' && (
            <button type="button" className="btn btn-primary" onClick={() => onNavigate('scm-weighing')}>
              Pesar mangas
            </button>
          )}
        </div>
      )}
    </section>
  );
}
