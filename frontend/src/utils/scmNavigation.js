const KNOWN_TABS = new Set([
  'legacy-home',
  'crear-ot',
  'pesar',
  'avance',
  'gestion',
  'cerrar-ops',
  'scm-prelabels',
  'scm-production',
  'scm-weighing',
  'scm-inventory-opening',
  'scm-prepared-material',
]);

const MODULE_BY_TAB = Object.freeze({
  'scm-production': 'production',
  'scm-prelabels': 'production',
  'scm-weighing': 'production',
  'scm-prepared-material': 'preparation',
  'scm-inventory-opening': 'inventory',
});

export const stationModuleFromTab = (tab = '') => MODULE_BY_TAB[tab] || 'legacy';

export const stationNavigationFromSearch = (search = '') => {
  const params = new URLSearchParams(search);
  const requestedTab = String(params.get('tab') || '').trim();
  return {
    activeTab: KNOWN_TABS.has(requestedTab) ? requestedTab : 'legacy-home',
    printJobId: String(params.get('job') || '').trim(),
  };
};
