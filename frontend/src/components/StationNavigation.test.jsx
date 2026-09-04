import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import StationNavigation from './StationNavigation';

describe('navegación visible de la estación piloto', () => {
  it('devuelve las tareas legacy a la cabecera y expone solo Producción en SCM', () => {
    const onNavigate = vi.fn();

    render(
      <StationNavigation
        activeTab="pesar"
        activeModule="legacy"
        onNavigate={onNavigate}
      />,
    );

    expect(screen.getByRole('button', { name: 'Crear OT' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Pesar OPs' }).getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('button', { name: 'Avance' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Gestión' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cerrar OPs' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Producción' })).toBeTruthy();

    expect(screen.queryByRole('button', { name: 'Sistema anterior' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Preparación' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Inventario' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Crear OT' }));
    expect(onNavigate).toHaveBeenCalledWith('crear-ot');
  });

  it('mantiene Producción activa en sus vistas internas', () => {
    render(
      <StationNavigation
        activeTab="scm-weighing"
        activeModule="production"
        onNavigate={() => {}}
      />,
    );

    expect(screen.getByRole('button', { name: 'Producción' }).getAttribute('aria-current')).toBe('page');
  });
});
