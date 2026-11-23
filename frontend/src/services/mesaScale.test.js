import { describe, expect, it, vi } from 'vitest';
import {
  captureMesaScale,
  getMesaScaleStatus,
  hasLiveScaleReading,
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
      modo: 'accura', disponible: true, base: 'NT', kg: '10.125', kg_en_vivo: '10.125', estable: null, mensaje: 'Lectura estable',
    });
    expect(fetcher).toHaveBeenCalledWith('/api/mesa/balanza');
  });

  it('keeps a stable zero as a live reading and forwards cancellation', async () => {
    const controller = new AbortController();
    const fetcher = vi.fn((_url, options) => {
      expect(options.signal).toBe(controller.signal);
      return response({ modo: 'accura', disponible: true, base: 'NT', kg: '0.0', mensaje: 'ST' });
    });

    await expect(getMesaScaleStatus(fetcher, { signal: controller.signal })).resolves.toMatchObject({
      modo: 'accura', disponible: true, base: 'NT', kg: '0.0', kg_en_vivo: '0.0', estable: null,
    });
    expect(hasLiveScaleReading('0.0')).toBe(true);
    expect(hasLiveScaleReading(null)).toBe(false);
    expect(hasLiveScaleReading('-0.1')).toBe(true);
  });

  it('does not turn an aborted live sample into a connection warning', async () => {
    const controller = new AbortController();
    const abort = new DOMException('The operation was aborted.', 'AbortError');
    const fetcher = vi.fn(() => Promise.reject(abort));

    await expect(getMesaScaleStatus(fetcher, { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
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
