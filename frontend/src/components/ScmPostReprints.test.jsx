import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { scmPostReprintsApi } from '../services/api';
import ScmPostReprints from './ScmPostReprints';

vi.mock('../services/api', () => ({ scmPostReprintsApi: { list: vi.fn(), print: vi.fn(), sync: vi.fn() } }));
describe('POST copies queue', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    scmPostReprintsApi.list.mockResolvedValue({ data: { jobs: [
      { copy_job_id: 'copy-1', estado: 'PENDIENTE', copias: 3, payload: { codigo_manga: 'OF80-OT71-M002' } },
    ] } });
  });
  it('never prints on loading and blocks double click and timeout replay', async () => {
    let fail;
    scmPostReprintsApi.print.mockReturnValue(new Promise((resolve, reject) => { fail = reject; }));
    render(<ScmPostReprints />);
    fireEvent.click(screen.getByText('Consultar copias autorizadas'));
    await screen.findByText('OF80-OT71-M002');
    expect(scmPostReprintsApi.print).not.toHaveBeenCalled();
    const button = screen.getByText('Imprimir copias autorizadas');
    fireEvent.click(button);
    fireEvent.click(button);
    fail(new Error('timeout'));
    await screen.findByText(/Sin conexión/);
    expect(scmPostReprintsApi.print).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Envío registrado; revisar estado').disabled).toBe(true);
  });
  it('syncs evidence without paper and distinguishes accepted from physical receipt', async () => {
    scmPostReprintsApi.print.mockResolvedValue({ data: { result: 'ACCEPTED' } });
    scmPostReprintsApi.sync.mockResolvedValue({ data: { jobs: [] } });
    render(<ScmPostReprints />);
    fireEvent.click(screen.getByText('Consultar copias autorizadas'));
    await screen.findByText('OF80-OT71-M002');
    fireEvent.click(screen.getByText('Imprimir copias autorizadas'));
    await screen.findByText(/Recepción física sin confirmar/);
    fireEvent.click(screen.getByText('Sincronizar evidencia'));
    await waitFor(() => expect(scmPostReprintsApi.sync).toHaveBeenCalledTimes(1));
    expect(scmPostReprintsApi.print).toHaveBeenCalledTimes(1);
  });
});
