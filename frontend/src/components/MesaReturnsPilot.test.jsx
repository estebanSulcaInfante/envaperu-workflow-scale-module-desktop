import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MesaReturnsPilot from './MesaReturnsPilot';

const answer = (value, status = 200) => Promise.resolve({
  ok: status >= 200 && status < 300,
  status,
  json: () => Promise.resolve(value),
});

const stubFetch = (fetcher) => vi.stubGlobal('fetch', (url, options) =>
  url === '/api/mesa/balanza'
    ? answer({ modo: 'manual', disponible: false, base: null, kg: null, mensaje: 'Entrada manual explícita' })
    : fetcher(url, options));

const units = [
  { code: 'OFDEMO-OT101-M001', piece: 'Manga 100', color: 'Azul', lot: 'LOTE-A', status: 'available', origins: [] },
  { code: 'OFDEMO-OT101-M002', piece: 'Manga 100', color: 'Azul', lot: 'LOTE-B', status: 'available', origins: [] },
  { code: 'OFDEMO-OT101-M004', piece: 'Manga 200', color: 'Azul', lot: 'LOTE-C', status: 'available', origins: [] },
];

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe('MesaReturnsPilot', () => {
  const scanCode = (label, code) => {
    const input = screen.getByLabelText(label);
    fireEvent.change(input, { target: { value: code } });
    fireEvent.submit(input.closest('form'));
  };

  it('explica el motivo junto al peso hasta que la lectura es válida', async () => {
    stubFetch(() => answer({ units, receipts: [] }));
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    scanCode('Escanear manga a recibir', units[0].code);
    const field = screen.getByLabelText('Peso NETO manual');
    for (const [value, hint] of [['-1','El peso debe ser mayor que 0 kg.'], ['0','El peso debe ser mayor que 0 kg.'], ['1,1234','Usa hasta 3 decimales.'], ['abc','Ingresa un peso en kg con coma o punto, por ejemplo 2,125.']]) {
      fireEvent.change(field, { target: { value } });
      expect(screen.getByText(hint).id).toBe(field.getAttribute('aria-describedby'));
      expect(screen.getByRole('button', { name: 'Pesar y recibir' }).disabled).toBe(true);
    }
    fireEvent.change(field, { target: { value: '2,125' } });
    expect(field.getAttribute('aria-invalid')).toBe('false');
    expect(screen.getByRole('button', { name: 'Pesar y recibir' }).disabled).toBe(false);
  });

  it.each(['pending','received'])('identifica la unión %s en ambas pestañas al leer un origen', async status => {
    const parent = { ...units[0], code: 'MESA-001', status, origins: [units[0].code] };
    stubFetch(() => answer({ units: [{ ...units[0], status: status === 'pending' ? 'reserved' : 'received' },parent], receipts: [] }));
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    if (status === 'pending') fireEvent.click(screen.getByText('Recibir otra manga mientras tanto'));
    const message = status === 'pending' ? 'Esta manga pertenece a MESA-001. Escanea el QR de MESA-001.' : 'Esta manga ya se recibió con la unión MESA-001. Consulta el comprobante de MESA-001.';
    scanCode('Escanear manga a recibir', units[0].code);
    await screen.findByText(message);
    fireEvent.click(screen.getByText(message).closest('[role="alert"]').querySelector('button'));
    fireEvent.click(screen.getByRole('tab', {name:'Unión de mangas'}));
    scanCode('Escanear manga de origen', units[0].code);
    await screen.findByText(message);
  });

  it('recupera el comprobante del ingreso concurrente con sus kilos confirmados', async () => {
    let finished = false;
    const receipt = { code: units[0].code, net_kg: '2.420', created_at: '2026-11-18T12:01:00Z' };
    stubFetch(url => {
      if (url.endsWith('/receive')) {
        finished = true;
        return answer({error:'La unidad no está disponible para recepción'},409);
      }
      return answer({ units: [{...units[0],status: finished ? 'received' : 'available'}], receipts:finished ? [receipt] : [] });
    });
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    scanCode('Escanear manga a recibir',units[0].code);
    fireEvent.change(screen.getByLabelText('Peso NETO manual'), { target:{value:'2,5'} });
    fireEvent.click(screen.getByRole('button', {name:'Pesar y recibir'}));
    await screen.findByText(/2.420 kg netos registrados/);
    expect(screen.getByRole('button', {name:'Ingreso ya registrado'}).disabled).toBe(true);
  });
  it('separa los controles del piloto y muestra la fecha y el turno de la OT', async () => {
    const unit = { ...units[0], ot_date: '2026-11-17', ot_shift: 'NOCHE' };
    stubFetch(vi.fn(() => answer({ units: [unit], receipts: [] })));
    const { rerender } = render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    expect(screen.queryByText(/Pruebas sin lector/)).toBeNull();
    rerender(<MesaReturnsPilot showExamples />);
    const toggle = screen.getByText(/Pruebas sin lector/);
    expect(toggle.closest('details').open).toBe(false);
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole('button', { name: 'Cargar código' }));
    const identity = screen.getByRole('region', { name: 'Manga escaneada' });
    expect(identity.textContent).toContain('17/11/2026 · Noche');
    expect(identity.textContent).not.toContain('LOTE-A');
  });

  it('carga estado, crea unión compatible y muestra su QR imprimible', async () => {
    const fetcher = vi.fn((url, options) => {
      if (url === '/api/mesa/state') return answer({ units, receipts: [] });
      if (url === '/api/mesa/unions') return answer({ code: 'UNION-001' });
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);

    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    fireEvent.click(screen.getByRole('tab', { name: 'Unión de mangas' }));
    const scan = screen.getByLabelText('Escanear manga de origen');
    fireEvent.change(scan, { target: { value: 'OFDEMO-OT101-M001' } });
    fireEvent.submit(scan.closest('form'));
    fireEvent.change(scan, { target: { value: 'OFDEMO-OT101-M002' } });
    fireEvent.submit(scan.closest('form'));
    fireEvent.click(screen.getByRole('button', { name: 'Crear identidad de unión' }));

    await screen.findByRole('img', { name: 'QR de UNION-001' });
    expect(fetcher.mock.calls.find(([url]) => url === '/api/mesa/unions')[1].body)
      .toBe(JSON.stringify({ codes: ['OFDEMO-OT101-M001', 'OFDEMO-OT101-M002'] }));
    expect(screen.getByRole('img', { name: 'QR de UNION-001' }).getAttribute('src')).toBe('/api/mesa/qr/UNION-001.svg');
    expect(screen.getByText(/escanee el QR nuevo/i)).toBeTruthy();
  });

  it('resuelve el JSON compacto PREPESAJE por label_id vigente al unir mangas', async () => {
    const labeledUnits = units.slice(0, 2).map((unit, index) => ({
      ...unit,
      aliases: [unit.code, `L1|00000000-0000-4000-8000-00000000000${index + 1}`, JSON.stringify({ v: 1, label_id: `00000000-0000-4000-8000-00000000000${index + 1}`, manga_id: 'no-confiar' })],
    }));
    const fetcher = vi.fn((url, options) => {
      if (url === '/api/mesa/state') return answer({ units: labeledUnits, receipts: [] });
      if (url === '/api/mesa/unions') return answer({ code: 'UNION-JSON-001' });
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);

    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    fireEvent.click(screen.getByRole('tab', { name: 'Unión de mangas' }));
    const scan = screen.getByLabelText('Escanear manga de origen');
    for (const labelId of ['00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002']) {
      fireEvent.change(scan, { target: { value: JSON.stringify({ label_id: labelId, v: 1 }) } });
      fireEvent.submit(scan.closest('form'));
    }
    fireEvent.click(screen.getByRole('button', { name: 'Crear identidad de unión' }));

    await screen.findByRole('img', { name: 'QR de UNION-JSON-001' });
    const union = fetcher.mock.calls.find(([url]) => url === '/api/mesa/unions');
    expect(JSON.parse(union[1].body)).toMatchObject({
      codes: [units[0].code, units[1].code],
      label_ids: { [units[0].code]: '00000000-0000-4000-8000-000000000001', [units[1].code]: '00000000-0000-4000-8000-000000000002' },
    });
  });

  it('resuelve el JSON compacto PREPESAJE por label_id vigente al pesar y recibir', async () => {
    const labeledUnit = {
      ...units[0],
      aliases: [units[0].code, 'L1|00000000-0000-4000-8000-000000000003', JSON.stringify({ v: 1, label_id: '00000000-0000-4000-8000-000000000003' })],
    };
    const fetcher = vi.fn((url, options) => {
      if (url === '/api/mesa/state') return answer({ units: [labeledUnit], receipts: [] });
      if (url === '/api/mesa/receive') return answer({ code: labeledUnit.code, net_kg: '2.125', created_at: '2026-11-20T12:00:00Z' });
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);

    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    const scan = screen.getByLabelText('Escanear manga a recibir');
    fireEvent.change(scan, { target: { value: '{"v":1,"label_id":"00000000-0000-4000-8000-000000000003"}' } });
    fireEvent.submit(scan.closest('form'));
    fireEvent.change(screen.getByLabelText('Peso NETO manual'), { target: { value: '2,125' } });
    fireEvent.click(screen.getByRole('button', { name: 'Pesar y recibir' }));

    await screen.findByText(/2.125 kg netos registrados/i);
    const receive = fetcher.mock.calls.find(([url]) => url === '/api/mesa/receive');
    expect(JSON.parse(receive[1].body)).toMatchObject({ code: labeledUnit.code, label_id: '00000000-0000-4000-8000-000000000003' });
  });

  it('conserva label_id al reintentar y no muta si Central invalida la etiqueta entre lecturas', async () => {
    const labelId = '00000000-0000-4000-8000-000000000005';
    const labeledUnit = { ...units[0], aliases: [units[0].code, JSON.stringify({ v: 1, label_id: labelId })] };
    let stateCalls = 0;
    const fetcher = vi.fn((url) => {
      if (url === '/api/mesa/state') {
        stateCalls += 1;
        return answer({ units: [{ ...labeledUnit, status: stateCalls > 1 ? 'reserved' : 'available' }], receipts: [] });
      }
      if (url === '/api/mesa/receive') return answer({ error: 'La etiqueta PREPESAJE ya no está vigente para esta manga.' }, 409);
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    fireEvent.change(screen.getByLabelText('Escanear manga a recibir'), { target: { value: JSON.stringify({ v: 1, label_id: labelId }) } });
    fireEvent.submit(screen.getByLabelText('Escanear manga a recibir').closest('form'));
    fireEvent.change(screen.getByLabelText('Peso NETO manual'), { target: { value: '2,125' } });
    fireEvent.click(screen.getByRole('button', { name: 'Pesar y recibir' }));
    await screen.findByText(/La manga ya no está disponible para este ingreso/i);
    const receive = fetcher.mock.calls.find(([url]) => url === '/api/mesa/receive');
    expect(JSON.parse(receive[1].body)).toMatchObject({ code: labeledUnit.code, label_id: labelId });
    expect(fetcher.mock.calls.filter(([url]) => url === '/api/mesa/receive')).toHaveLength(1);
  });

  it('rechaza JSON PREPESAJE inválido, desconocido o con campos manipulables', async () => {
    const labeledUnit = {
      ...units[0],
      aliases: [units[0].code, JSON.stringify({ v: 1, label_id: '00000000-0000-4000-8000-000000000004' })],
    };
    stubFetch(() => answer({ units: [labeledUnit], receipts: [] }));
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    const scan = screen.getByLabelText('Escanear manga a recibir');

    fireEvent.change(scan, { target: { value: '{"v":1,"label_id":' } });
    fireEvent.submit(scan.closest('form'));
    await screen.findByText(/QR PREPESAJE inválido/i);

    fireEvent.change(scan, { target: { value: '{"v":1,"label_id":"00000000-0000-4000-8000-000000000099"}' } });
    fireEvent.submit(scan.closest('form'));
    await screen.findByText(/Etiqueta PREPESAJE desconocida o no vigente/i);

    fireEvent.change(scan, { target: { value: '{"v":1,"label_id":"00000000-0000-4000-8000-000000000099","code":"OFDEMO-OT101-M001"}' } });
    fireEvent.submit(scan.closest('form'));
    await screen.findByText(/Etiqueta PREPESAJE desconocida o no vigente/i);
    expect(screen.queryByText(/Manga escaneada/)).toBeNull();
  });

  it('mantiene Unión activa para escanear, pesar y confirmar la identidad nueva', async () => {
    const fetcher = vi.fn((url) => {
      if (url === '/api/mesa/state') return answer({ units, receipts: [] });
      if (url === '/api/mesa/unions') return answer({ code: 'UNION-001' });
      if (url === '/api/mesa/receive') return answer({ code: 'UNION-001', net_kg: '4.250', created_at: '2026-11-18T12:00:00Z' });
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);

    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    fireEvent.click(screen.getByRole('tab', { name: 'Unión de mangas' }));
    const originScan = screen.getByLabelText('Escanear manga de origen');
    for (const code of [units[0].code, units[1].code]) {
      fireEvent.change(originScan, { target: { value: code } });
      fireEvent.submit(originScan.closest('form'));
    }
    fireEvent.click(screen.getByRole('button', { name: 'Crear identidad de unión' }));

    await screen.findByRole('img', { name: 'QR de UNION-001' });
    expect(screen.getByRole('tab', { name: 'Unión de mangas' }).getAttribute('aria-selected')).toBe('true');
    const newQr = screen.getByLabelText('Escanear QR nuevo');
    await waitFor(() => expect(document.activeElement).toBe(newQr));
    fireEvent.change(newQr, { target: { value: 'UNION-001' } });
    fireEvent.submit(newQr.closest('form'));
    fireEvent.change(screen.getByLabelText('Peso NETO manual'), { target: { value: '4,250' } });
    fireEvent.click(screen.getByRole('button', { name: 'Pesar y recibir' }));

    await screen.findByText(/4.250 kg netos registrados/i);
    await screen.findByText(/Retorno confirmado: UNION-001/);
    expect(screen.queryByText(/No pudimos verificar el ingreso/)).toBeNull();
    expect(fetcher.mock.calls.filter(([url]) => url === '/api/mesa/receive')).toHaveLength(1);
  });

  it('sale explícitamente de Unión para recibir una manga individual y no mezcla su peso', async () => {
    const fetcher = vi.fn((url) => {
      if (url === '/api/mesa/state') return answer({ units, receipts: [] });
      if (url === '/api/mesa/unions') return answer({ code: 'UNION-001' });
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);

    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    fireEvent.click(screen.getByRole('tab', { name: 'Unión de mangas' }));
    const originScan = screen.getByLabelText('Escanear manga de origen');
    for (const code of [units[0].code, units[1].code]) {
      fireEvent.change(originScan, { target: { value: code } });
      fireEvent.submit(originScan.closest('form'));
    }
    fireEvent.click(screen.getByRole('button', { name: 'Crear identidad de unión' }));
    await screen.findByRole('img', { name: 'QR de UNION-001' });

    fireEvent.click(screen.getByRole('button', { name: 'Ir a retorno individual' }));
    expect(screen.getByRole('tab', { name: 'Pesar y recibir' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByLabelText('Escanear manga a recibir')).toBeTruthy();
    expect(screen.getByLabelText('Peso NETO manual').disabled).toBe(true);
  });

  it('captura Accura dentro de Unión y liga el token al QR UNION', async () => {
    const fetcher = vi.fn((url) => {
      if (url === '/api/mesa/state') return answer({ units, receipts: [] });
      if (url === '/api/mesa/balanza') return answer({ modo: 'accura', disponible: true, base: 'NT', kg: null, mensaje: 'ST' });
      if (url === '/api/mesa/unions') return answer({ code: 'UNION-001' });
      if (url === '/api/mesa/balanza/capturas') return answer({ kg: '5.125', scale_token: 'scale-union-1' });
      if (url === '/api/mesa/receive') return answer({ code: 'UNION-001', net_kg: '5.125', created_at: '2026-11-18T12:00:00Z' });
      return answer({ error: 'ruta no esperada' }, 404);
    });
    vi.stubGlobal('fetch', fetcher);

    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza Accura conectada · esperando lectura');
    fireEvent.click(screen.getByRole('tab', { name: 'Unión de mangas' }));
    const originScan = screen.getByLabelText('Escanear manga de origen');
    for (const code of [units[0].code, units[1].code]) {
      fireEvent.change(originScan, { target: { value: code } });
      fireEvent.submit(originScan.closest('form'));
    }
    fireEvent.click(screen.getByRole('button', { name: 'Crear identidad de unión' }));
    await screen.findByRole('img', { name: 'QR de UNION-001' });
    const newQr = screen.getByLabelText('Escanear QR nuevo');
    fireEvent.change(newQr, { target: { value: 'UNION-001' } });
    fireEvent.submit(newQr.closest('form'));
    fireEvent.click(screen.getByRole('button', { name: 'Leer balanza' }));
    await screen.findByText(/Lectura Accura capturada para UNION-001/);
    fireEvent.click(screen.getByRole('button', { name: 'Pesar y recibir' }));
    await screen.findByText(/5.125 kg netos registrados/i);

    const capture = fetcher.mock.calls.find(([url]) => url === '/api/mesa/balanza/capturas');
    expect(JSON.parse(capture[1].body)).toMatchObject({ codigo: 'UNION-001' });
    const receive = fetcher.mock.calls.find(([url]) => url === '/api/mesa/receive');
    expect(JSON.parse(receive[1].body)).toMatchObject({ code: 'UNION-001', scale_token: 'scale-union-1' });
  });

  it('no recibe una unión si no se escanea su nueva identidad y envía el peso como string', async () => {
    const fetcher = vi.fn((url, options) => {
      if (url === '/api/mesa/state') return answer({ units, receipts: [] });
      if (url === '/api/mesa/unions') return answer({ code: 'UNION-001' });
      if (url === '/api/mesa/receive') return answer({ code: 'UNION-001', net_kg: '12.340', created_at: '2026-11-18T12:00:00Z' });
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    fireEvent.click(screen.getByRole('tab', { name: 'Unión de mangas' }));
    const scan = screen.getByLabelText('Escanear manga de origen');
    for (const code of ['OFDEMO-OT101-M001', 'OFDEMO-OT101-M002']) {
      fireEvent.change(scan, { target: { value: code } });
      fireEvent.submit(scan.closest('form'));
    }
    fireEvent.click(await screen.findByRole('button', { name: 'Crear identidad de unión' }));
    await screen.findByRole('img', { name: 'QR de UNION-001' });
    fireEvent.change(screen.getByLabelText('Escanear QR nuevo'), { target: { value: 'UNION-001' } });
    fireEvent.submit(screen.getByLabelText('Escanear QR nuevo').closest('form'));
    fireEvent.change(screen.getByLabelText('Peso NETO manual'), { target: { value: '12,340' } });
    fireEvent.click(screen.getByRole('button', { name: 'Pesar y recibir' }));
    await screen.findByText(/12.340 kg netos registrados/i);
    const receive = fetcher.mock.calls.find(([url]) => url === '/api/mesa/receive');
    expect(JSON.parse(receive[1].body)).toMatchObject({ code: 'UNION-001', net_kg: '12.340' });
  });

  it('reintenta una respuesta perdida con el mismo request_id y no cambia la manga', async () => {
    let receiveCalls = 0;
    const fetcher = vi.fn((url) => {
      if (url === '/api/mesa/state') return answer({ units, receipts: [] });
      if (url === '/api/mesa/receive') {
        receiveCalls += 1;
        return receiveCalls === 1
          ? answer({ error: 'Sin conexión después de enviar' }, 503)
          : answer({ code: 'OFDEMO-OT101-M001', net_kg: '3.125', created_at: '2026-11-18T12:01:00Z' });
      }
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    const scan = screen.getByLabelText('Escanear manga a recibir');
    fireEvent.change(scan, { target: { value: 'OFDEMO-OT101-M001' } });
    fireEvent.submit(scan.closest('form'));
    fireEvent.change(screen.getByLabelText('Peso NETO manual'), { target: { value: '3.125' } });
    fireEvent.click(screen.getByRole('button', { name: 'Pesar y recibir' }));
    await screen.findByText(/No pudimos verificar el ingreso\. Reintenta con el mismo peso/);
    fireEvent.click(screen.getByRole('button', { name: 'Pesar y recibir' }));
    await screen.findByText(/3.125 kg netos registrados/i);
    const posts = fetcher.mock.calls.filter(([url]) => url === '/api/mesa/receive');
    expect(JSON.parse(posts[0][1].body).request_id).toBe(JSON.parse(posts[1][1].body).request_id);
    expect(JSON.parse(posts[0][1].body).code).toBe('OFDEMO-OT101-M001');
    expect(JSON.parse(posts[0][1].body).net_kg).toBe(JSON.parse(posts[1][1].body).net_kg);
  });

  it('exige exactamente el QR de la unión pendiente y conserva el destino ante un origen recibido', async () => {
    const pending = { code: 'MESA-001', piece: 'Manga 100', color: 'Azul', lot: null, status: 'pending', origins: ['OFDEMO-OT101-M001'] };
    const fetcher = vi.fn((url) => url === '/api/mesa/state'
      ? answer({ units: [{ ...units[0], status: 'received' }, units[1], pending], receipts: [] })
      : answer({ error: 'ruta no esperada' }, 404));
    window.localStorage.setItem('mesa-returns-pilot.pending-union', JSON.stringify({ ...pending, origins: [{ ...units[0], status: 'received' }] }));
    stubFetch(fetcher);

    render(<MesaReturnsPilot />);
    const scan = await screen.findByLabelText('Escanear QR nuevo');
    fireEvent.change(scan, { target: { value: units[0].code } });
    fireEvent.submit(scan.closest('form'));

    await screen.findByText(new RegExp(`Esperaba MESA-001\\. Escaneaste ${units[0].code}\\.`));
    expect(screen.getByText(/Esta manga pertenece a MESA-001/)).toBeTruthy();
    expect(screen.getByLabelText('Peso NETO manual').disabled).toBe(true);
    expect(screen.getByLabelText('Escanear QR nuevo')).toBeTruthy();
  });

  it('muestra el rechazo literal de pieza y color, incluido el conflicto del servidor', async () => {
    const fetcher = vi.fn((url) => {
      if (url === '/api/mesa/state') return answer({ units: [...units], receipts: [] });
      if (url === '/api/mesa/unions') return answer({ error: 'orígenes incompatibles' }, 409);
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    fireEvent.click(screen.getByRole('tab', { name: 'Unión de mangas' }));
    const scan = screen.getByLabelText('Escanear manga de origen');
    for (const code of [units[0].code, units[2].code]) {
      fireEvent.change(scan, { target: { value: code } });
      fireEvent.submit(scan.closest('form'));
    }
    await screen.findByText('No se puede unir: pieza y color deben coincidir');

    fireEvent.change(scan, { target: { value: units[1].code } });
    fireEvent.submit(scan.closest('form'));
    fireEvent.click(screen.getByRole('button', { name: 'Crear identidad de unión' }));
    await screen.findByText('No se puede unir: pieza y color deben coincidir');
  });

  it('mantiene una unión creada aunque falle la recarga posterior y explica cómo retomarla', async () => {
    let stateCalls = 0;
    const fetcher = vi.fn((url) => {
      if (url === '/api/mesa/state') {
        stateCalls += 1;
        return stateCalls === 1 ? answer({ units, receipts: [] }) : Promise.reject(new TypeError('fetch failed'));
      }
      if (url === '/api/mesa/unions') return answer({ code: 'MESA-001' });
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    fireEvent.click(screen.getByRole('tab', { name: 'Unión de mangas' }));
    const scan = screen.getByLabelText('Escanear manga de origen');
    for (const code of [units[0].code, units[1].code]) {
      fireEvent.change(scan, { target: { value: code } });
      fireEvent.submit(scan.closest('form'));
    }
    fireEvent.click(screen.getByRole('button', { name: 'Crear identidad de unión' }));
    await screen.findByText(/Identidad MESA-001 creada\. Pulsa Reintentar para actualizar las mangas/);
    expect(screen.getByRole('img', { name: 'QR de MESA-001' })).toBeTruthy();
  });

  it('permite repetir una confirmación con comprobante 2xx inutilizable conservando peso y clave', async () => {
    let receiveCalls = 0;
    const fetcher = vi.fn((url) => {
      if (url === '/api/mesa/state') return answer({ units, receipts: [] });
      if (url === '/api/mesa/receive') {
        receiveCalls += 1;
        return receiveCalls === 1 ? answer({}) : answer({ code: units[0].code, net_kg: '3.125', created_at: '2026-11-18T12:02:00Z' });
      }
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    const scan = screen.getByLabelText('Escanear manga a recibir');
    fireEvent.change(scan, { target: { value: units[0].code } });
    fireEvent.submit(scan.closest('form'));
    fireEvent.change(screen.getByLabelText('Peso NETO manual'), { target: { value: '3,125' } });
    fireEvent.click(screen.getByRole('button', { name: 'Pesar y recibir' }));
    await screen.findByText(/No pudimos verificar el ingreso\. Reintenta con el mismo peso/);
    fireEvent.click(screen.getByRole('button', { name: 'Pesar y recibir' }));
    await screen.findByText(/3.125 kg netos registrados/i);
    const posts = fetcher.mock.calls.filter(([url]) => url === '/api/mesa/receive');
    expect(JSON.parse(posts[0][1].body)).toEqual(JSON.parse(posts[1][1].body));
  });

  it('ofrece reintentar cuando no puede cargar el estado sin inventar mangas', async () => {
    let stateCalls = 0;
    const fetcher = vi.fn((url) => {
      if (url !== '/api/mesa/state') return answer({ error: 'ruta no esperada' }, 404);
      stateCalls += 1;
      return stateCalls === 1 ? Promise.reject(new TypeError('fetch failed')) : answer({ units, receipts: [] });
    });
    stubFetch(fetcher);
    render(<MesaReturnsPilot showExamples />);
    await screen.findByText('No se pudo cargar el estado de mangas. Revise la conexión y vuelva a intentar.');
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeTruthy();
    expect(screen.queryByText(units[0].code)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    await screen.findByText('Balanza manual');
    expect(screen.getByText(units[0].code)).toBeTruthy();
  });

  it('captura Accura NT bajo demanda y conserva scale_token en el retorno', async () => {
    const fetcher = vi.fn((url) => {
      if (url === '/api/mesa/state') return answer({ units, receipts: [] });
      if (url === '/api/mesa/balanza') return answer({ modo: 'accura', disponible: true, base: 'NT', kg: null, mensaje: 'ST' });
      if (url === '/api/mesa/balanza/capturas') return answer({ kg: '3.125', scale_token: 'scale-1' });
      if (url === '/api/mesa/receive') return answer({ code: units[0].code, net_kg: '3.125', created_at: '2026-11-19T01:00:00Z' });
      return answer({ error: 'ruta no esperada' }, 404);
    });
    vi.stubGlobal('fetch', fetcher);
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza Accura conectada · esperando lectura');
    scanCode('Escanear manga a recibir', units[0].code);
    fireEvent.click(screen.getByRole('button', { name: 'Leer balanza' }));
    await screen.findByText(/Lectura Accura capturada/);
    fireEvent.click(screen.getByRole('button', { name: 'Pesar y recibir' }));
    await screen.findByText(/3.125 kg netos registrados/);
    const receive = fetcher.mock.calls.find(([url]) => url === '/api/mesa/receive');
    expect(JSON.parse(receive[1].body)).toMatchObject({ code: units[0].code, scale_token: 'scale-1' });
  });

  it('envía dos copias del sticker de retorno a la cola seleccionada sin volver a recibir', async () => {
    const receipt = { code: units[0].code, net_kg: '2.420', created_at: '2026-11-18T12:01:00Z' };
    const fetcher = vi.fn((url, options) => {
      if (url === '/api/mesa/state') return answer({ units: [{ ...units[0], status: 'received' }], receipts: [receipt] });
      if (url === '/api/mesa/printer/status') return answer({ available: ['TSC-ESTACION-2'], connected: true });
      if (url.endsWith('/retornos/etiquetas/OFDEMO-OT101-M001/print')) return answer({ status: 'QUEUED', printer_name: 'TSC-ESTACION-2', copies: 2 });
      return answer({ error: 'ruta no esperada' }, 404);
    });
    stubFetch(fetcher);
    render(<MesaReturnsPilot />);
    await screen.findByText('Balanza manual');
    scanCode('Escanear manga a recibir', units[0].code);
    await screen.findByText(/2.420 kg netos registrados/);
    fireEvent.click(screen.getAllByRole('button', { name: 'Seleccionar impresora Windows' })[0]);
    fireEvent.change((await screen.findAllByLabelText('Cola Windows'))[0], { target: { value: 'TSC-ESTACION-2' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Imprimir 2 copias' })[0]);
    await screen.findByText(/2 copias enviadas/);
    const printCall = fetcher.mock.calls.find(([url]) => url.endsWith('/retornos/etiquetas/OFDEMO-OT101-M001/print'));
    expect(JSON.parse(printCall[1].body)).toEqual({ printer_name: 'TSC-ESTACION-2' });
    expect(fetcher.mock.calls.some(([url]) => url === '/api/mesa/receive')).toBe(false);
  });
});
