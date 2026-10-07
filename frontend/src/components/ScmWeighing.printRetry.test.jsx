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

    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr-format-error' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('Listo para cierre final');
    fireEvent.keyDown(window, { key: 'F2' });

    await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Pesaje central confirmado')).toBeTruthy();
    expect(screen.getByText(/el pesaje est� confirmado; la etiqueta no fue emitida/i)).toBeTruthy();
    expect(screen.getByText(/no se releer.*ni se crear/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Reintentar solo emisi/ })).toBeTruthy();
    expect(screen.getByLabelText('QR de manga SCM').disabled).toBe(true);

    const firstCall = scmWeighingApi.confirm.mock.calls[0];
    const retryButton = screen.getByRole('button', { name: /Reintentar solo emisi/ });
    fireEvent.click(retryButton);
    fireEvent.click(retryButton);
    await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(2));
    expect(scmWeighingApi.confirm.mock.calls[1]).toEqual(firstCall);
    expect(screen.getByText('Etiqueta final: IMPRESA')).toBeTruthy();
  });
});
