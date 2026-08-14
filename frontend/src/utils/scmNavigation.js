const KNOWN_TABS = new Set([
  'crear-ot',
  'pesar',
  'avance',
  'gestion',
  'cerrar-ops',
  'scm-prelabels',
  'scm-weighing',
]);

export const stationNavigationFromSearch = (search = '') => {
  const params = new URLSearchParams(search);
  const requestedTab = String(params.get('tab') || '').trim();
  return {
    activeTab: KNOWN_TABS.has(requestedTab) ? requestedTab : 'crear-ot',
    printJobId: String(params.get('job') || '').trim(),
  };
};
