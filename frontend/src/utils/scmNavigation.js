const KNOWN_TABS = new Set([
  'crear-ot',
  'pesar',
  'avance',
  'gestion',
  'cerrar-ops',
  'scm-prelabels',
  'scm-production',
  'scm-weighing',
]);

const PILOT_REDIRECTS = Object.freeze({
  'legacy-home': 'crear-ot',
  'scm-inventory-opening': 'scm-production',
  'scm-prepared-material': 'scm-production',
});

const MODULE_BY_TAB = Object.freeze({
  'scm-production': 'production',
  'scm-prelabels': 'production',
  'scm-weighing': 'production',
});

export const stationModuleFromTab = (tab = '') => MODULE_BY_TAB[tab] || 'legacy';

export const stationNavigationFromSearch = (search = '') => {
  const params = new URLSearchParams(search);
  const requestedTab = String(params.get('tab') || '').trim();
  const redirectedTab = PILOT_REDIRECTS[requestedTab];
  return {
    activeTab: redirectedTab || (KNOWN_TABS.has(requestedTab) ? requestedTab : 'crear-ot'),
    printJobId: String(params.get('job') || '').trim(),
  };
};
