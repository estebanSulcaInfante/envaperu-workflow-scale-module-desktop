import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import ScmProductionHome from './ScmProductionHome';

describe('ScmProductionHome', () => {
  it('presenta tareas dentro de Producción sin convertirlas en módulos globales', () => {
    const onNavigate = vi.fn();
    render(<ScmProductionHome onNavigate={onNavigate} />);

    expect(screen.getByRole('heading', { name: 'Producción' })).toBeTruthy();
    expect(screen.getByText(/ningún escaneo ejecuta una operación/i)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /preparar etiquetas/i }));
    expect(onNavigate).toHaveBeenCalledWith('scm-prelabels');

    fireEvent.click(screen.getByRole('button', { name: /pesar mangas/i }));
    expect(onNavigate).toHaveBeenCalledWith('scm-weighing');
  });
});
