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
      activeTab: 'crear-ot',
      printJobId: 'job-001',
    });
  });

  it('oculta por URL los módulos fuera del alcance UAT y elimina el inicio legacy intermedio', () => {
    expect(stationNavigationFromSearch('?tab=legacy-home')).toEqual({
      activeTab: 'crear-ot',
      printJobId: '',
    });
    expect(stationNavigationFromSearch('?tab=scm-prepared-material')).toEqual({
      activeTab: 'scm-production',
      printJobId: '',
    });
    expect(stationNavigationFromSearch('?tab=scm-inventory-opening')).toEqual({
      activeTab: 'scm-production',
      printJobId: '',
    });
  });

  it('agrupa solamente las vistas liberadas dentro de Producción', () => {
    expect(stationModuleFromTab('scm-production')).toBe('production');
    expect(stationModuleFromTab('scm-prelabels')).toBe('production');
    expect(stationModuleFromTab('scm-weighing')).toBe('production');
    expect(stationModuleFromTab('scm-prepared-material')).toBe('legacy');
    expect(stationModuleFromTab('scm-inventory-opening')).toBe('legacy');
    expect(stationModuleFromTab('crear-ot')).toBe('legacy');
  });
});
