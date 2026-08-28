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

const otherLabel = {
  ...label,
  public_id: 'label-002',
  payload: {
    ...label.payload,
    codigo_manga: 'OF0014-OT006-M009',
    of_ot: 'OF-000014 - OT-000006',
    op_ot: undefined,
    pieza_color: 'Florero italiano',
    color: 'BLANCO',
    maquinista: 'María Torres',
    qr: { label_id: 'label-002' },
  },
};

const otherJob = {
  print_job_id: 'job-002',
  plantilla_version: 'PREPESAJE_TSPL_1',
  labels: [otherLabel],
};


describe('ScmPrelabels', () => {
  beforeEach(() => {
    vi.resetAllMocks();
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
    fireEvent.click(screen.getByRole('button', { name: /seleccionar asa fucsia/i }));

    await waitFor(() => {
      expect(scmPrelabelsApi.preview).toHaveBeenCalledWith('job-001');
    });
  });

  it('identifica los trabajos por pieza, color y OF/OT antes que por UUID', async () => {
    scmPrelabelsApi.pending.mockResolvedValue({
      data: {
        print_jobs: [{ ...otherJob, status: 'PENDING' }],
        count: 1,
      },
    });

    render(<ScmPrelabels />);

    expect(await screen.findByText('Florero italiano · BLANCO')).toBeTruthy();
    expect(screen.getByText('OF-000014 - OT-000006')).toBeTruthy();
    expect(screen.queryByText('job-002')).toBeNull();
    expect(screen.getByText('Búsqueda por ID técnico')).toBeTruthy();
  });

  it('filtra la bandeja cargada con datos humanos y marca la selección', async () => {
    scmPrelabelsApi.pending.mockResolvedValue({
      data: {
        print_jobs: [job, otherJob],
        count: 2,
      },
    });
    scmPrelabelsApi.preview.mockResolvedValue({ data: { print_job: otherJob } });

    render(<ScmPrelabels />);

    const filter = await screen.findByRole('searchbox', {
      name: 'Buscar por pieza, color, OF/OT, manga o maquinista',
    });
    fireEvent.change(filter, { target: { value: 'florero blanco' } });

    expect(screen.getByText('Florero italiano · BLANCO')).toBeTruthy();
    expect(screen.queryByText('Asa fucsia · FUCSIA')).toBeNull();

    const selectJob = screen.getByRole('button', {
      name: /seleccionar florero italiano/i,
    });
    fireEvent.click(selectJob);

    await waitFor(() => expect(selectJob.getAttribute('aria-pressed')).toBe('true'));
    expect(await screen.findByRole('region', { name: 'Trabajo seleccionado' })).toBeTruthy();
  });

  it('limpia el detalle anterior si falla la siguiente consulta', async () => {
    scmPrelabelsApi.pending.mockResolvedValue({
      data: { print_jobs: [job, otherJob], count: 2 },
    });
    scmPrelabelsApi.preview
      .mockResolvedValueOnce({ data: { print_job: job } })
      .mockRejectedValueOnce({ response: { data: { message: 'Central no disponible' } } });

    render(<ScmPrelabels />);

    fireEvent.click(await screen.findByRole('button', { name: /seleccionar asa fucsia/i }));
    expect(await screen.findByRole('button', { name: 'Imprimir sticker' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /seleccionar florero italiano/i }));

    expect(await screen.findByText('Central no disponible')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Imprimir sticker' })).toBeNull();
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

    fireEvent.click(screen.getByText('Búsqueda por ID técnico'));
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

    fireEvent.click(screen.getByText('Búsqueda por ID técnico'));
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
      'Trabajo enviado y acuse técnico registrado. Verifique que salieron todas las hojas.',
    )).toBeTruthy();
  });

  it('muestra un estado inequívoco mientras envía el trabajo a imprimir', async () => {
    scmPrelabelsApi.preview.mockResolvedValue({ data: { print_job: job } });
    scmPrelabelsApi.print.mockImplementation(() => new Promise(() => {}));
    render(<ScmPrelabels initialJobId="job-001" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Imprimir sticker' }));

    const printing = screen.getByRole('button', { name: 'Imprimiendo…' });
    expect(printing.disabled).toBe(true);
  });

  it('distingue un trabajo ya impreso y evita una reimpresión accidental', async () => {
    scmPrelabelsApi.preview.mockResolvedValue({
      data: { print_job: { ...job, status: 'PRINTED' } },
    });
    render(<ScmPrelabels />);

    fireEvent.click(screen.getByText('Búsqueda por ID técnico'));
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

  it('trata una emisión interrumpida como incierta y no ofrece retry', async () => {
    scmPrelabelsApi.preview.mockResolvedValue({
      data: {
        print_job: {
          ...job,
          status: 'PENDING',
          local_print_state: 'EMISION_INCIERTA',
          auto_reprint_blocked: true,
          labels: [{ ...label, local_print_state: 'EMISION_INCIERTA' }],
        },
      },
    });
    render(<ScmPrelabels initialJobId="job-001" />);

    expect(await screen.findByText(/no reimprima este trabajo/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Reintentar impresión' })).toBeNull();
    expect(screen.getByRole('button', {
      name: 'Requiere etiqueta de reemplazo',
    }).disabled).toBe(true);
  });

  it('reanuda un acuse pendiente sin presentar la acción como reimpresión', async () => {
    const pendingAckJob = {
      ...job,
      status: 'PENDING',
      local_print_state: 'IMPRESA',
      ack_pending: true,
      labels: [{ ...label, local_print_state: 'IMPRESA' }],
    };
    scmPrelabelsApi.preview.mockResolvedValue({
      data: { print_job: pendingAckJob },
    });
    scmPrelabelsApi.print.mockResolvedValue({
      data: {
        print_job: {
          print_job_id: 'job-001',
          local_print_state: 'IMPRESA',
          labels: [{ public_id: 'label-001', local_print_state: 'IMPRESA' }],
        },
        result: 'IMPRESA',
        ack_pending: false,
        ack_recovered: true,
      },
    });
    render(<ScmPrelabels initialJobId="job-001" />);

    const resume = await screen.findByRole('button', {
      name: 'Reanudar acuse central',
    });
    expect(resume.disabled).toBe(false);
    expect(screen.getByText(/solo falta el acuse central/i)).toBeTruthy();
    fireEvent.click(resume);

    await waitFor(() => expect(scmPrelabelsApi.print).toHaveBeenCalledWith('job-001'));
    expect(await screen.findByText(/no se volvió a imprimir/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Sticker ya impreso' }).disabled).toBe(true);
  });
});
