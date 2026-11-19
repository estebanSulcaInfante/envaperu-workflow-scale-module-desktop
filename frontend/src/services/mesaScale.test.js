import { describe, expect, it, vi } from 'vitest';
import {
  captureMesaScale,
  getMesaScaleStatus,
} from './mesaScale';

const response = (value, status = 200) => Promise.resolve({
  ok: status >= 200 && status < 300,
  status,
  json: () => Promise.resolve(value),
});

describe('mesa scale contract', () => {
  it('normalizes the explicit manual/Accura status contract', async () => {
    const fetcher = vi.fn(() => response({
      modo: 'accura', disponible: true, base: 'NT', kg: '10.125', mensaje: 'Lectura estable',
    }));

    await expect(getMesaScaleStatus(fetcher)).resolves.toEqual({
      modo: 'accura', disponible: true, base: 'NT', kg: '10.125', mensaje: 'Lectura estable',
    });
    expect(fetcher).toHaveBeenCalledWith('/api/mesa/balanza');
  });

  it('captures and retries the same code with the same token and idempotency key', async () => {
    const fetcher = vi.fn(() => response({ kg: '8.500', capture_token: 'cap-2' }));
    await captureMesaScale({ codigo: 'INV-001', token: 'cap-1', operationId: 'op-1', fetcher });
    await captureMesaScale({ codigo: 'INV-001', token: 'cap-2', operationId: 'op-1', fetcher });

    expect(fetcher).toHaveBeenNthCalledWith(1, '/api/mesa/balanza/capturas', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'Idempotency-Key': 'op-1' }),
      body: JSON.stringify({ codigo: 'INV-001', scale_token: 'cap-1' }),
    }));
    expect(fetcher).toHaveBeenNthCalledWith(2, '/api/mesa/balanza/capturas', expect.objectContaining({
      body: JSON.stringify({ codigo: 'INV-001', scale_token: 'cap-2' }),
    }));
  });
});
