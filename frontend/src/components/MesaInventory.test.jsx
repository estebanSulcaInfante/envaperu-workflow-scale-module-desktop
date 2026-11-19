import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MesaInventory from './MesaInventory';

const state = {
  zonas: [{ id: 'Z1', nombre: 'C66' }, { id: 'Z2', nombre: 'Mesa' }],
  articulos: [{ id: 'A1', nombre: 'TAPA', color: 'AZUL' }],
  mangas: [{ codigo: 'C66-001', articulo: 'A1', zona: 'Z1', estado: 'disponible', neto: null }],
  sesiones: [],
  pendientes: [{ codigo: 'MESA-001', articulo: 'TAPA', zona: 'Z2', estado: 'pendiente', bruto: '', tara: '0', neto: null }],
  movimientos: [{ id: 'MOV-1', codigo: 'MESA-001', estado: 'pendiente' }],
};

const answer = (value, status = 200) => Promise.resolve({
  ok: status >= 200 && status < 300,
  status,
  json: () => Promise.resolve(value),
});

const stubFetch = (fetcher) => vi.stubGlobal('fetch', (url, options) =>
  url === '/api/mesa/balanza'
    ? answer({ modo: 'manual', disponible: false, base: null, kg: null, mensaje: 'Entrada manual explícita' })
    : fetcher(url, options));

afterEach(() => vi.unstubAllGlobals());

describe('MesaInventory', () => {
  it('abre sesión C66, conserva el lector enfocado y permite aceptar discrepancia de zona', async () => {
    let discrepancy = true;
    const fetcher = vi.fn((url, options) => {
      if (url.endsWith('/estado')) return answer({ ...state, sesiones: [{ id: 'S1', zona: 'Z1', estado: 'abierta', lecturas: [] }] });
      if (url.endsWith('/sesiones') && options?.method === 'POST') return answer({ id: 'S1' });
      if (url.endsWith('/lecturas') && options?.method === 'POST' && discrepancy) {
        discrepancy = false;
        return answer({ error: 'La zona no coincide', zona_anterior: 'Z2' }, 409);
      }
      if (url.endsWith('/lecturas') && options?.method === 'POST') return answer({ mensaje: 'ok' });
      return answer({});
    });
    stubFetch(fetcher);

    render(<MesaInventory initialView="c66" />);
    await screen.findByRole('heading', { name: 'Inventario C66' });
    await screen.findByRole('option', { name: 'C66' });
    fireEvent.change(screen.getByLabelText('Zona'), { target: { value: 'Z1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Iniciar sesión C66' }));
    await waitFor(() => expect(screen.getByLabelText('Zona').disabled).toBe(true));
    const scanner = await screen.findByLabelText('Escanear QR de manga');
    fireEvent.change(scanner, { target: { value: 'C66-001' } });
    fireEvent.submit(scanner.closest('form'));
    await screen.findByText('La zona no coincide');
    expect(screen.getByRole('button', { name: /Sí, registrar en/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Sí, registrar en/ }));
    await screen.findByText(/C66-001 registrada en/);
    const lectureCall = fetcher.mock.calls.filter(([url]) => url.endsWith('/sesiones/S1/lecturas'));
    expect(JSON.parse(lectureCall[1][1].body)).toMatchObject({ codigo: 'C66-001', confirmar_zona: true, zona_anterior: 'Z2' });
  });

  it('pesa un pendiente con bruto/tara, muestra el mismo QR y confirma con motivo', async () => {
    const fetcher = vi.fn((url, options) => {
      if (url.endsWith('/estado')) return answer(state);
      if (url.endsWith('/pesajes')) return answer({ codigo: 'MESA-001', neto: '8.500' });
      if (url.endsWith('/confirmaciones')) return answer({ codigo: 'MESA-001', movimiento_id: 1 });
      return answer({});
    });
    stubFetch(fetcher);
    render(<MesaInventory initialView="mesa" />);
    await screen.findByRole('button', { name: /MESA-001/ });
    fireEvent.click(screen.getByRole('button', { name: /MESA-001/ }));
    fireEvent.change(screen.getByLabelText('Peso bruto (kg)'), { target: { value: '10,000' } });
    fireEvent.change(screen.getByLabelText('Tara (kg)'), { target: { value: '1,500' } });
    fireEvent.click(screen.getByRole('button', { name: 'Registrar pesaje' }));
    await screen.findByRole('img', { name: 'QR de MESA-001' });
    const image = screen.getByRole('img', { name: 'QR de MESA-001' });
    expect(image.getAttribute('src')).toContain('/etiquetas/MESA-001/pesaje.svg?formato=50x50');
    fireEvent.change(screen.getByLabelText('Motivo de confirmación'), { target: { value: 'Retorno recibido en mesa' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar ingreso' }));
    await screen.findByText('Ingreso MESA-001 confirmado.');
    expect(screen.queryByText('Comprobante AJ-0001')).toBeNull();
    const confirmCall = fetcher.mock.calls.find(([url]) => url.endsWith('/confirmaciones'));
    expect(JSON.parse(confirmCall[1].body)).toMatchObject({ codigo: 'MESA-001', motivo: 'Retorno recibido en mesa' });
  });

  it('selecciona una cola Windows y envía dos copias sin crear otro pesaje', async () => {
    const fetcher = vi.fn((url, options) => {
      if (url.endsWith('/estado')) return answer(state);
      if (url === '/api/mesa/printer/status') return answer({ available: ['TSC-ESTACION-2'], connected: true });
      if (url.endsWith('/pesajes')) return answer({ codigo: 'MESA-001', neto: '8.500' });
      if (url.endsWith('/etiquetas/MESA-001/pesaje/print')) return answer({ status: 'QUEUED', printer_name: 'TSC-ESTACION-2', copies: 2 });
      return answer({});
    });
    stubFetch(fetcher);
    render(<MesaInventory initialView="mesa" />);
    fireEvent.click(await screen.findByRole('button', { name: /MESA-001/ }));
    fireEvent.change(screen.getByLabelText('Peso bruto (kg)'), { target: { value: '10,000' } });
    fireEvent.change(screen.getByLabelText('Tara (kg)'), { target: { value: '1,500' } });
    fireEvent.click(screen.getByRole('button', { name: 'Registrar pesaje' }));
    await screen.findByRole('button', { name: 'Seleccionar impresora Windows' });
    fireEvent.click(screen.getByRole('button', { name: 'Seleccionar impresora Windows' }));
    fireEvent.change(await screen.findByLabelText('Cola Windows'), { target: { value: 'TSC-ESTACION-2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Imprimir 2 copias' }));
    await screen.findByText(/2 copias enviadas/);
    const printCall = fetcher.mock.calls.find(([url]) => url.endsWith('/pesaje/print'));
    expect(JSON.parse(printCall[1].body)).toEqual({ printer_name: 'TSC-ESTACION-2' });
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/pesajes')).length).toBe(1);
  });

  it('crea una manga sin identidad en la mesa y deja seleccionado su pesaje', async () => {
    let createdRequest = false;
    const created = {
      ...state,
      pendientes: [
        ...state.pendientes,
        { codigo: 'INV-MESA-001', articulo: 'A1', zona: 'Z2', estado: 'pendiente', bruto: '', tara: '0', neto: null },
      ],
    };
    const fetcher = vi.fn((url, options) => {
      if (url.endsWith('/estado')) return answer(createdRequest ? created : state);
      if (url.endsWith('/antiguas') && options?.method === 'POST') {
        createdRequest = true;
        return answer({ codigo: 'INV-MESA-001' }, 201);
      }
      return answer({});
    });
    stubFetch(fetcher);
    render(<MesaInventory initialView="mesa" />);
    fireEvent.change(await screen.findByLabelText('Zona'), { target: { value: 'Z2' } });
    fireEvent.change(screen.getByLabelText('Artículo'), { target: { value: 'A1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Registrar manga sin identidad' }));
    await screen.findByRole('button', { name: /INV-MESA-001/ });
    expect(screen.getByLabelText('Peso bruto (kg)')).toBeTruthy();
    const call = fetcher.mock.calls.find(([url]) => url.endsWith('/antiguas'));
    expect(JSON.parse(call[1].body)).toMatchObject({ codigo: '', articulo: 'A1', zona: 'Z2' });
  });

  it('reutiliza una etiqueta reservada escaneada en la mesa y permite cancelarla', async () => {
    let linked = false;
    const fetcher = vi.fn((url, options) => {
      if (url.endsWith('/estado')) return answer({
        ...state,
        preetiquetas: linked ? [] : [{ codigo: 'INV-001', estado: 'RESERVADA' }],
        pendientes: linked
          ? [...state.pendientes, { codigo: 'INV-001', articulo: 'A1', zona: 'Z2', estado: 'pendiente', bruto: '', tara: '0', neto: null }]
          : state.pendientes,
      });
      if (url.endsWith('/antiguas') && options?.method === 'POST') {
        linked = true;
        return answer({ codigo: 'INV-001' }, 200);
      }
      return answer({});
    });
    stubFetch(fetcher);
    render(<MesaInventory initialView="mesa" />);
    const scanner = await screen.findByLabelText('Escanear identidad');
    fireEvent.change(scanner, { target: { value: 'INV-001' } });
    fireEvent.submit(scanner.closest('form'));
    await screen.findByText(/se reutilizará esta etiqueta/);
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar selección' }));
    expect(screen.queryByText(/se reutilizará esta etiqueta/)).toBeNull();
    fireEvent.change(scanner, { target: { value: 'INV-001' } });
    fireEvent.submit(scanner.closest('form'));
    await screen.findByText(/se reutilizará esta etiqueta/);
    fireEvent.change(screen.getByLabelText('Zona'), { target: { value: 'Z2' } });
    fireEvent.change(screen.getByLabelText('Artículo'), { target: { value: 'A1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Registrar manga sin identidad' }));
    await screen.findByLabelText('Peso bruto (kg)');
    const call = fetcher.mock.calls.find(([url]) => url.endsWith('/antiguas'));
    expect(JSON.parse(call[1].body)).toMatchObject({ codigo: 'INV-001', articulo: 'A1', zona: 'Z2' });
  });

  it('separa revisión, búsqueda y faltante con confirmación en PC', async () => {
    const fetcher = vi.fn((url) => {
      if (url.endsWith('/estado')) return answer(state);
      if (url.endsWith('/revision')) return answer({ token: 'REV-1', neto: '8.500' });
      if (url.endsWith('/faltantes')) return answer({ codigo: 'MESA-001' });
      return answer({});
    });
    stubFetch(fetcher);
    render(<MesaInventory initialView="revision" />);
    expect((await screen.findAllByRole('heading', { name: 'Revisión de faltantes', level: 2 })).length).toBe(2);
    fireEvent.change(screen.getByLabelText('Código a revisar'), { target: { value: 'MESA-001' } });
    fireEvent.click(screen.getByLabelText('Cobertura revisada'));
    fireEvent.click(screen.getByLabelText('Movimientos revisados'));
    fireEvent.click(screen.getByLabelText('Búsqueda completada'));
    fireEvent.click(screen.getByRole('button', { name: 'Registrar revisión' }));
    await screen.findByText('Neto informado: 8.500 kg');
    fireEvent.change(screen.getByLabelText('Motivo del faltante'), { target: { value: 'No apareció en ubicación' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar faltante' }));
    await waitFor(() => expect(screen.getByText('Faltante de MESA-001 confirmado.')).toBeTruthy());
    expect(fetcher.mock.calls.some(([url]) => url.endsWith('/revision'))).toBe(true);
    expect(fetcher.mock.calls.some(([url]) => url.endsWith('/faltantes'))).toBe(true);
  });

  it('recupera por QR una recepción confirmada y deja su etiqueta disponible sin duplicar confirmación', async () => {
    const recovered = {
      ...state,
      pendientes: [],
      mangas: [{ ...state.mangas[0], codigo: 'MESA-001', estado: 'DISPONIBLE', neto: '8.500' }],
      movimientos: [...state.movimientos, { codigo: 'MESA-001', tipo: 'REINGRESO' }],
    };
    const fetcher = vi.fn((url) => url.endsWith('/estado') ? answer(recovered) : answer({}));
    stubFetch(fetcher);
    render(<MesaInventory initialView="mesa" />);
    const scanner = await screen.findByLabelText('Escanear identidad');
    fireEvent.change(scanner, { target: { value: 'MESA-001' } });
    fireEvent.submit(scanner.closest('form'));
    await screen.findByText('Estado: confirmado');
    expect(screen.getByRole('button', { name: 'Ingreso confirmado' }).disabled).toBe(true);
    expect(screen.getByRole('img', { name: 'QR de MESA-001' })).toBeTruthy();
    expect(fetcher.mock.calls.some(([url]) => url.endsWith('/confirmaciones'))).toBe(false);
  });

  it('captura Accura GS como bruto y envía scale_token con tara local', async () => {
    const fetcher = vi.fn((url) => {
      if (url.endsWith('/estado')) return answer(state);
      if (url === '/api/mesa/balanza') return answer({ modo: 'accura', disponible: true, base: 'GS', kg: null, mensaje: 'ST' });
      if (url === '/api/mesa/balanza/capturas') return answer({ kg: '10.000', scale_token: 'scale-gs-1' });
      if (url.endsWith('/pesajes')) return answer({ codigo: 'MESA-001', neto: '8.500' });
      return answer({});
    });
    vi.stubGlobal('fetch', fetcher);
    render(<MesaInventory initialView="mesa" />);
    await screen.findByText('Balanza Accura conectada · esperando lectura');
    fireEvent.click(await screen.findByRole('button', { name: /MESA-001/ }));
    fireEvent.change(screen.getByLabelText('Tara (kg)'), { target: { value: '1,500' } });
    fireEvent.click(screen.getByRole('button', { name: 'Leer balanza' }));
    await screen.findByText(/Lectura Accura capturada/);
    fireEvent.click(screen.getByRole('button', { name: 'Registrar pesaje' }));
    const weighing = fetcher.mock.calls.find(([url]) => url.endsWith('/pesajes'));
    expect(JSON.parse(weighing[1].body)).toMatchObject({ bruto: '10.000', tara: '1.500', scale_token: 'scale-gs-1' });
    expect(JSON.parse(weighing[1].body).confirmar_sin_tara_indicador).toBeUndefined();
  });

  it('en base NT exige confirmar balanza sin tara y envía esa evidencia una sola vez', async () => {
    const fetcher = vi.fn((url) => {
      if (url.endsWith('/estado')) return answer(state);
      if (url === '/api/mesa/balanza') return answer({ modo: 'accura', disponible: true, base: 'NT', kg: null, mensaje: 'ST' });
      if (url === '/api/mesa/balanza/capturas') return answer({ kg: '10.000', scale_token: 'scale-nt-1' });
      if (url.endsWith('/pesajes')) return answer({ codigo: 'MESA-001', neto: '8.500' });
      return answer({});
    });
    vi.stubGlobal('fetch', fetcher);
    render(<MesaInventory initialView="mesa" />);
    await screen.findByText('Balanza Accura conectada · esperando lectura');
    fireEvent.click(await screen.findByRole('button', { name: /MESA-001/ }));
    expect(screen.getByRole('button', { name: 'Leer balanza' }).disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox', { name: /balanza está sin tara/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Leer balanza' }));
    await screen.findByText(/Lectura Accura capturada/);
    fireEvent.click(screen.getByRole('button', { name: 'Registrar pesaje' }));
    const weighing = fetcher.mock.calls.find(([url]) => url.endsWith('/pesajes'));
    expect(JSON.parse(weighing[1].body)).toMatchObject({ scale_token: 'scale-nt-1', confirmar_sin_tara_indicador: true });
  });
});

