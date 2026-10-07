import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { scmWeighingApi } from '../services/api';
import ScmWeighing from './ScmWeighing';

vi.mock('../services/api', () => ({
  scmWeighingApi: {
    resolve: vi.fn(),
    control: vi.fn(),
    confirm: vi.fn(),
  },
}));

const context = {
  can_weigh: true,
  can_register_shift_cut: false,
  can_register_weight_control: false,
  scanned_label_id: '10000000-0000-4000-8000-000000000001',
  continuidad: { ultimo_control: null },
  manga: {
    codigo: 'OP0084-OT001-M001',
    op_ot: 'OP0084 - OT-000001',
    fecha_operativa: '2026-07-28',
    maquinista: 'Juan Perez',
    pieza_color: 'Asa fucsia',
    color: 'FUCSIA',
    tipo: 'NORMAL',
    tara_nominal_kg: '0.100',
    peso_fabricado_teorico_kg: '10.000',
  },
};

describe('ScmWeighing print retry', () => {
  beforeEach(() => vi.clearAllMocks());

  it('conserva peso confirmado y reintenta solo emision con el mismo operation id', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    scmWeighingApi.confirm
      .mockResolvedValueOnce({
        data: {
          confirmed: { weighing: { estado_manga: 'PESADA', peso_fisico_neto_kg: '10.000', kg_produccion_ot: '10.000' } },
          print_result: {
            result: 'NOT_EMITTED',
            error_code: 'PRINT_FORMAT_INVALID',
            error: 'Formato de etiqueta invalido',
            expected_bytes: 0,
            bytes_written: 0,
            write_attempted: false,
            recoverable: true,
            retry_same_operation: true,
          },
        },
      })
      .mockResolvedValueOnce({
        data: {
          confirmed: { weighing: { estado_manga: 'PESADA', peso_fisico_neto_kg: '10.000', kg_produccion_ot: '10.000' } },
          print_result: { result: 'IMPRESA' },
        },
      });

    const firstView = render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr-format-error' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('Listo para cierre final');
    fireEvent.keyDown(window, { key: 'F2' });

    await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Pesaje central confirmado')).toBeTruthy();
    expect(screen.getByText(/el pesaje esta confirmado; la etiqueta no fue emitida/i)).toBeTruthy();
    expect(screen.getByText(/no se releer.*ni se crear/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Reintentar solo emisi/ })).toBeTruthy();
    expect(screen.getByLabelText('QR de manga SCM').disabled).toBe(true);

    const firstCall = scmWeighingApi.confirm.mock.calls[0];
    expect(sessionStorage.getItem('scm-weighing:pending-print:v1')).toBeTruthy();
    firstView.unmount();
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    await screen.findByText('Pesaje central confirmado');
    expect(scmWeighingApi.resolve).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /Reintentar solo emisi/ })).toBeTruthy();
    const retryButton = screen.getByRole('button', { name: /Reintentar solo emisi/ });
    fireEvent.click(retryButton);
    fireEvent.click(retryButton);
    await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(2));
    expect(scmWeighingApi.confirm.mock.calls[1]).toEqual(firstCall);
    expect(screen.getByText('Etiqueta final: IMPRESA')).toBeTruthy();
  });
  it('ignora envelope manipulado y elimina JSON corrupto sin resolver ni reintentar', async () => {
    sessionStorage.setItem('scm-weighing:pending-print:v1', JSON.stringify({
      version: 1,
      operation_id: '30000000-0000-4000-8000-000000000001',
      scanned_label_id: '30000000-0000-4000-8000-000000000002',
      context: { ...context, scanned_label_id: '30000000-0000-4000-8000-000000000003' },
      result: { print_result: { result: 'NOT_EMITTED' } },
    }));
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    expect(screen.queryByText('Pesaje confirmado; etiqueta no emitida')).toBeNull();
    expect(sessionStorage.getItem('scm-weighing:pending-print:v1')).toBeNull();

    sessionStorage.setItem('scm-weighing:pending-print:v1', '{corrupt');
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    expect(sessionStorage.getItem('scm-weighing:pending-print:v1')).toBeNull();
  });

  it('limpia el envelope cuando el reintento queda incierto y no lo ofrece tras recargar', async () => {
    sessionStorage.clear();
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    scmWeighingApi.confirm
      .mockResolvedValueOnce({
        data: {
          confirmed: { weighing: { estado_manga: 'PESADA', peso_fisico_neto_kg: '10.000', kg_produccion_ot: '10.000' } },
          print_result: {
            result: 'NOT_EMITTED',
            error_code: 'PRINT_FORMAT_INVALID',
            expected_bytes: 0,
            bytes_written: 0,
            write_attempted: false,
            retry_same_operation: true,
          },
        },
      })
      .mockResolvedValueOnce({
        data: {
          confirmed: { weighing: { estado_manga: 'PESADA', peso_fisico_neto_kg: '10.000', kg_produccion_ot: '10.000' } },
          print_result: {
            result: 'EMISION_INCIERTA',
            error_code: 'PRINTER_TIMEOUT',
            bytes_written: 4,
            write_attempted: true,
            retry_same_operation: false,
          },
        },
      });

    const firstView = render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr-uncertain' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('Listo para cierre final');
    fireEvent.keyDown(window, { key: 'F2' });
    await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByRole('button', { name: /Reintentar solo emisi/ }));
    await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(2));
    expect(sessionStorage.getItem('scm-weighing:pending-print:v1')).toBeNull();
    expect(screen.queryByRole('button', { name: /Reintentar solo emisi/ })).toBeNull();

    firstView.unmount();
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /Reintentar solo emisi/ })).toBeNull();
    expect(scmWeighingApi.resolve).toHaveBeenCalledTimes(1);
  });

  it('avisa honestamente si sessionStorage no puede conservar la emision pendiente', async () => {
    sessionStorage.clear();
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    scmWeighingApi.confirm.mockResolvedValue({
      data: {
        confirmed: { weighing: { estado_manga: 'PESADA', peso_fisico_neto_kg: '10.000', kg_produccion_ot: '10.000' } },
        print_result: { result: 'NOT_EMITTED', error_code: 'PRINT_FORMAT_INVALID', bytes_written: 0, write_attempted: false },
      },
    });
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    try {
      render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
      const scanner = screen.getByLabelText('QR de manga SCM');
      fireEvent.change(scanner, { target: { value: 'qr-storage-failure' } });
      fireEvent.keyDown(scanner, { key: 'Enter' });
      await screen.findByText('Listo para cierre final');
      fireEvent.keyDown(window, { key: 'F2' });
      await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(1));
      expect(await screen.findByText(/No se pudo conservar la emision pendiente/)).toBeTruthy();
      expect(sessionStorage.getItem('scm-weighing:pending-print:v1')).toBeNull();
    } finally {
      setItemSpy.mockRestore();
    }
  });
});
