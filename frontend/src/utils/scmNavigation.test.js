import { describe, expect, it } from 'vitest';

import { stationNavigationFromSearch } from './scmNavigation';

describe('navegación profunda de la estación', () => {
  it('abre Etiquetas SCM y conserva el trabajo solicitado', () => {
    expect(stationNavigationFromSearch('?tab=scm-prelabels&job=job-001')).toEqual({
      activeTab: 'scm-prelabels',
      printJobId: 'job-001',
    });
  });

  it('ignora pestañas desconocidas sin romper el flujo legacy', () => {
    expect(stationNavigationFromSearch('?tab=desconocida&job=job-001')).toEqual({
      activeTab: 'crear-ot',
      printJobId: 'job-001',
    });
  });
});
