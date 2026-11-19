import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MesaNotices, useMesaNotices } from './MesaNotices';

function Harness() {
  const api = useMesaNotices();
  return (
    <>
      <button type="button" onClick={() => api.notify({ message: 'Lectura guardada', type: 'success' })}>Avisar éxito</button>
      <button type="button" onClick={() => api.notify({ message: 'Central sin respuesta', type: 'error' })}>Avisar error</button>
      <button type="button" onClick={() => api.notify({ message: 'Aviso adicional', type: 'info' })}>Avisar adicional</button>
      <button type="button" onClick={() => api.notify({ message: 'Aviso cuatro', type: 'info' })}>Avisar cuarto</button>
      <button type="button" onClick={() => api.notify({ message: 'Duración limitada', type: 'info', autoHideDuration: 9000 })}>Avisar duración larga</button>
      <MesaNotices notices={api.notices} dismiss={api.dismiss} />
    </>
  );
}

afterEach(() => {
  vi.useRealTimers();
});

describe('MesaNotices', () => {
  it('expira cada aviso después de cinco segundos desde su propia creación', () => {
    vi.useFakeTimers();
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Avisar éxito' }));
    act(() => { vi.advanceTimersByTime(4500); });
    fireEvent.click(screen.getByRole('button', { name: 'Avisar error' }));
    expect(screen.getByRole('status').textContent).toContain('Lectura guardada');
    expect(screen.getByRole('alert').textContent).toContain('Central sin respuesta');
    act(() => { vi.advanceTimersByTime(500); });
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByRole('alert').textContent).toContain('Central sin respuesta');
    act(() => { vi.advanceTimersByTime(4500); });
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('permite cerrar manualmente un aviso y limita la cola visible a tres', () => {
    vi.useFakeTimers();
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Avisar éxito' }));
    fireEvent.click(screen.getByRole('button', { name: 'Avisar error' }));
    fireEvent.click(screen.getByRole('button', { name: 'Avisar adicional' }));
    fireEvent.click(screen.getByRole('button', { name: 'Avisar cuarto' }));
    expect(screen.getByText('Aviso cuatro')).toBeTruthy();
    expect(screen.getAllByTestId('mesa-notice-region')[0].children).toHaveLength(3);
    fireEvent.click(screen.getAllByRole('button', { name: 'Cerrar notificación' })[0]);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('reinicia el duplicado visible y nunca supera cinco segundos', () => {
    vi.useFakeTimers();
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Avisar éxito' }));
    act(() => { vi.advanceTimersByTime(4000); });
    fireEvent.click(screen.getByRole('button', { name: 'Avisar éxito' }));
    act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.getByRole('status').textContent).toContain('Lectura guardada');
    act(() => { vi.advanceTimersByTime(4000); });
    expect(screen.queryByRole('status')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Avisar duración larga' }));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.queryByText('Duración limitada')).toBeNull();
  });
});
