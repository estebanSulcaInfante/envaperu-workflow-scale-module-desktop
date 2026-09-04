import { describe, expect, it } from 'vitest';

import { stationModuleFromTab, stationNavigationFromSearch } from './scmNavigation';

describe('navegación profunda de la estación', () => {
  it('abre Etiquetas SCM y conserva el trabajo solicitado', () => {
    expect(stationNavigationFromSearch('?tab=scm-prelabels&job=job-001')).toEqual({
      activeTab: 'scm-prelabels',
      printJobId: 'job-001',
    });
  });

  it('ignora pestañas desconocidas sin romper el flujo legacy', () => {
    expect(stationNavigationFromSearch('?tab=desconocida&job=job-001')).toEqual({
      activeTab: 'legacy-home',
      printJobId: 'job-001',
    });
  });

  it('agrupa las vistas internas bajo tres módulos SCM', () => {
    expect(stationModuleFromTab('scm-production')).toBe('production');
    expect(stationModuleFromTab('scm-prelabels')).toBe('production');
    expect(stationModuleFromTab('scm-weighing')).toBe('production');
    expect(stationModuleFromTab('scm-prepared-material')).toBe('preparation');
    expect(stationModuleFromTab('scm-inventory-opening')).toBe('inventory');
    expect(stationModuleFromTab('crear-ot')).toBe('legacy');
  });
});
