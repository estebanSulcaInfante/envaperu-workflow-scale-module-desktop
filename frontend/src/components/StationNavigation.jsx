const LEGACY_TABS = [
  ['crear-ot', '📋', 'Crear OT'],
  ['pesar', '⚖️', 'Pesar OPs'],
  ['avance', '📈', 'Avance'],
  ['gestion', '📦', 'Gestión'],
  ['cerrar-ops', '🔒', 'Cerrar OPs'],
];

export default function StationNavigation({ activeTab, activeModule, onNavigate }) {
  return (
    <nav className="tab-nav" aria-label="Flujos del módulo de pesaje">
      <div className="tab-group tab-group-legacy" aria-label="Flujo legacy temporal">
        <span className="tab-group-label tab-group-label-legacy">Legacy temporal</span>
        <div className="tab-group-actions">
          {LEGACY_TABS.map(([tab, icon, label]) => (
            <button
              key={tab}
              type="button"
              className={`tab-btn ${activeTab === tab ? 'active' : ''}`}
              aria-label={label}
              aria-current={activeTab === tab ? 'page' : undefined}
              onClick={() => onNavigate(tab)}
            >
              <span aria-hidden="true">{icon}</span>{' '}{label}
            </button>
          ))}
        </div>
      </div>

      <div className="tab-group tab-group-scm" aria-label="Nuevo flujo SCM habilitado en UAT">
        <span className="tab-group-label tab-group-label-scm">Nuevo · SCM</span>
        <div className="tab-group-actions">
          <button
            type="button"
            className={`tab-btn ${activeModule === 'production' ? 'active' : ''}`}
            aria-current={activeModule === 'production' ? 'page' : undefined}
            onClick={() => onNavigate('scm-production')}
          >
            Producción
          </button>
        </div>
      </div>
    </nav>
  );
}
