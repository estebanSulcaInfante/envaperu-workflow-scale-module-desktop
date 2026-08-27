import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { scmPrelabelsApi } from '../services/api';
import ScmPrelabels from './ScmPrelabels';


vi.mock('../services/api', () => ({
  scmPrelabelsApi: {
    pending: vi.fn(),
    preview: vi.fn(),
    print: vi.fn(),
  },
}));

const label = {
  public_id: 'label-001',
  payload: {
    codigo_manga: 'OP0084-OT001-M001',
    op_ot: 'OP0084 - OT-000001',
    fecha_ot: '2026-07-28',
    maquinista: 'Juan Perez',
    pieza_color: 'Asa fucsia',
    color: 'FUCSIA',
    tipo_manga: 'NORMAL',
    qr: { label_id: 'label-001' },
  },
};

const job = {
  print_job_id: 'job-001',
  plantilla_version: 'PREPESAJE_TSPL_1',
  labels: [label],
};


describe('ScmPrelabels', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    scmPrelabelsApi.pending.mockResolvedValue({ data: { print_jobs: [], count: 0 } });
  });

  it('abre y previsualiza automáticamente el trabajo recibido por deep-link', async () => {
    scmPrelabelsApi.preview.mockResolvedValue({ data: { print_job: job } });

    render(<ScmPrelabels initialJobId="job-001" />);

    await waitFor(() => {
      expect(scmPrelabelsApi.preview).toHaveBeenCalledWith('job-001');
    });
    expect(screen.getByLabelText('ID del trabajo de impresión').value).toBe('job-001');
    expect(await screen.findByText('OP0084-OT001-M001')).toBeTruthy();
  });

  it('muestra una bandeja accesible de pendientes y permite abrir uno', async () => {
    scmPrelabelsApi.pending.mockResolvedValue({
      data: {
        print_jobs: [{ ...job, status: 'PENDING', created_at: '2026-08-09T15:00:00Z' }],
        count: 1,
      },
    });
    scmPrelabelsApi.preview.mockResolvedValue({ data: { print_job: job } });

    render(<ScmPrelabels />);

    expect(await screen.findByRole('heading', {
      name: 'Pendientes de impresión',
    })).toBeTruthy();
    expect(screen.getByText('Pendiente de impresión')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Previsualizar trabajo job-001' }));

    await waitFor(() => {
      expect(scmPrelabelsApi.preview).toHaveBeenCalledWith('job-001');
    });
  });

  it('mantiene la búsqueda manual si la estación todavía no ofrece la bandeja', async () => {
    scmPrelabelsApi.pending.mockRejectedValue({ response: { status: 404 } });

    render(<ScmPrelabels />);

    expect(await screen.findByText(/búsqueda manual sigue disponible/i)).toBeTruthy();
    expect(screen.getByLabelText('ID del trabajo de impresión')).toBeTruthy();
  });

  it('previsualiza dos copias físicas de la misma identidad', async () => {
    scmPrelabelsApi.preview.mockResolvedValue({ data: { print_job: job } });
    render(<ScmPrelabels />);

    fireEvent.change(
      screen.getByPlaceholderText('UUID del trabajo de impresión'),
      { target: { value: 'job-001' } },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Previsualizar' }));

    expect(await screen.findByText('OP0084-OT001-M001')).toBeTruthy();
    expect(screen.getByText('2 copias físicas de la misma identidad')).toBeTruthy();
    expect(screen.getByText('QR: label-001')).toBeTruthy();
  });

  it('imprime el mismo trabajo y muestra el acuse central', async () => {
    scmPrelabelsApi.preview.mockResolvedValue({ data: { print_job: job } });
    scmPrelabelsApi.print.mockResolvedValue({
      data: { print_job: job, result: 'IMPRESA' },
    });
    render(<ScmPrelabels />);

    fireEvent.change(
      screen.getByPlaceholderText('UUID del trabajo de impresión'),
      { target: { value: 'job-001' } },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Previsualizar' }));
    fireEvent.click(await screen.findByRole('button', {
      name: 'Imprimir sticker',
    }));

    await waitFor(() => {
      expect(scmPrelabelsApi.print).toHaveBeenCalledWith('job-001');
    });
    expect(await screen.findByText(
      'Resultado: IMPRESA. Acuse central registrado.',
    )).toBeTruthy();
  });

  it('distingue un trabajo ya impreso y evita una reimpresión accidental', async () => {
    scmPrelabelsApi.preview.mockResolvedValue({
      data: { print_job: { ...job, status: 'PRINTED' } },
    });
    render(<ScmPrelabels />);

    fireEvent.change(
      screen.getByPlaceholderText('UUID del trabajo de impresión'),
      { target: { value: 'job-001' } },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Previsualizar' }));

    expect(await screen.findByText(/estos stickers ya fueron impresos/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Sticker ya impreso' }).disabled).toBe(true);
  });

  it('permite reintentar cuando la impresora confirmó que no emitió el sticker', async () => {
    scmPrelabelsApi.preview.mockResolvedValue({
      data: {
        print_job: {
          ...job,
          status: 'FALLIDO',
          labels: [{ ...label, estado: 'FALLIDA_SIN_EMISION' }],
        },
      },
    });
    scmPrelabelsApi.print.mockResolvedValue({
      data: { print_job: job, result: 'IMPRESA' },
    });
    render(<ScmPrelabels initialJobId="job-001" />);

    const retry = await screen.findByRole('button', { name: 'Reintentar impresión' });
    expect(retry.disabled).toBe(false);
    fireEvent.click(retry);
    await waitFor(() => expect(scmPrelabelsApi.print).toHaveBeenCalledWith('job-001'));
  });

  it('bloquea la reimpresión ciega cuando la emisión quedó incierta', async () => {
    scmPrelabelsApi.preview.mockResolvedValue({
      data: {
        print_job: {
          ...job,
          status: 'FALLIDO',
          labels: [{ ...label, estado: 'EMISION_INCIERTA' }],
        },
      },
    });
    render(<ScmPrelabels initialJobId="job-001" />);

    expect(await screen.findByText(/no reimprima este trabajo/i)).toBeTruthy();
    const replacement = screen.getByRole('button', {
      name: 'Requiere etiqueta de reemplazo',
    });
    expect(replacement.disabled).toBe(true);
  });
});
