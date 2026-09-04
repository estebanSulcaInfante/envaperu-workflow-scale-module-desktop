const LEGACY_TASKS = [
  ['crear-ot', 'Crear OT', 'Genera el sticker de una orden con el contrato anterior.'],
  ['pesar', 'Pesar OP', 'Captura pesajes posicionales del flujo anterior.'],
  ['avance', 'Avance', 'Consulta el tablero histórico de producción.'],
  ['gestion', 'Gestión', 'Revisa y corrige registros legacy.'],
  ['cerrar-ops', 'Cerrar OP', 'Ejecuta el cierre administrativo anterior.'],
];

export default function LegacyModuleHome({ onNavigate }) {
  return (
    <section className="scm-module-home legacy-module-home" aria-labelledby="legacy-module-title">
      <div className="scm-module-home-heading">
        <span>Continuidad temporal</span>
        <h1 id="legacy-module-title">Sistema anterior</h1>
        <p>Utiliza estas funciones solo para documentos que todavía pertenecen al flujo legacy. Las nuevas operaciones deben iniciar en SCM.</p>
      </div>
      <div className="legacy-module-task-grid">
        {LEGACY_TASKS.map(([tab, title, description]) => (
          <button type="button" className="scm-module-task legacy-module-task" key={tab} onClick={() => onNavigate(tab)}>
            <strong>{title}</strong>
            <small>{description}</small>
            <span className="scm-module-task-cta">Abrir →</span>
          </button>
        ))}
      </div>
    </section>
  );
}
