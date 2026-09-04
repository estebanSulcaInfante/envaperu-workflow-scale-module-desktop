import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ScmInventoryOpening from './ScmInventoryOpening';
import ScmPreparedMaterialWeighing from './ScmPreparedMaterialWeighing';

const jsonResponse = (payload, ok = true) => Promise.resolve({
  ok,
  json: () => Promise.resolve(payload),
});

describe('contextos físicos SCM', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('Enter resuelve una apertura antes de habilitar F2', async () => {
    const fetchMock = vi.fn().mockReturnValue(jsonResponse({
      opening_id: '10000000-0000-4000-8000-000000000001',
      opening_codigo: 'AI-20260820-ABC',
      material_scm_id: 1,
      material_codigo: 'MP-PP-CLARIFICADO',
      material_nombre: 'PP clarificado',
      ubicacion_codigo: 'A-ENVA-MP-GEN',
      estado_calidad: 'LIBERADO',
      unidad_medida: 'KG',
      unidades_logisticas: [{
        id: '40000000-0000-4000-8000-000000000001', codigo: 'UL-EXISTENTE',
        qr_value: 'SCM:UL:40000000-0000-4000-8000-000000000001',
        articulo_codigo: 'MP-PP-CLARIFICADO', articulo_nombre: 'PP clarificado',
        ubicacion_codigo: 'A-ENVA-MP-GEN', estado_calidad: 'LIBERADO',
        peso_bruto_kg: '25.100', tara_kg: '0.100', peso_neto_kg: '25.000',
        created_at: '2026-08-24T15:30:00-05:00',
      }],
    }));
    vi.stubGlobal('fetch', fetchMock);
    render(<ScmInventoryOpening peso={25.1} listening simulationEnabled onSimulateWeight={vi.fn()} />);

    const scanner = screen.getByPlaceholderText(/QR de apertura física/);
    const confirm = screen.getByRole('button', { name: 'Registrar bolsa (F2)' });
    expect(confirm.disabled).toBe(true);
    fireEvent.change(scanner, { target: { value: JSON.stringify({
      type: 'SCM_INVENTORY_OPENING_TARGET', v: 1,
      opening_id: '10000000-0000-4000-8000-000000000001',
      material_scm_id: 1, ubicacion_codigo: 'A-ENVA-MP-GEN',
    }) } });
    fireEvent.keyDown(scanner, { key: 'Enter' });

    expect(await screen.findByText(/Contexto aceptado: PP clarificado/)).toBeTruthy();
    expect(screen.getByLabelText('Material activo').textContent).toContain('PP clarificado');
    expect(screen.getByText('AI-20260820-ABC')).toBeTruthy();
    expect(screen.getByText('UL-EXISTENTE')).toBeTruthy();
    expect(screen.getByText('NET ACUMULADO').parentElement.textContent).toContain('25.000 kg');
    expect(confirm.disabled).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('previsualiza el TSPL real y distingue una impresion simulada', async () => {
    const unitId = '40000000-0000-4000-8000-000000000001';
    const unit = {
      id: unitId,
      codigo: 'UL-EXISTENTE',
      qr_value: `SCM:UL:${unitId}`,
      articulo_codigo: 'MP-PP-CLARIFICADO',
      articulo_nombre: 'PP clarificado',
      ubicacion_codigo: 'A-ENVA-MP-GEN',
      estado_calidad: 'LIBERADO',
      peso_bruto_kg: '25.100',
      tara_kg: '0.100',
      peso_neto_kg: '25.000',
      created_at: '2026-08-24T15:30:00-05:00',
    };
    const fetchMock = vi.fn()
      .mockReturnValueOnce(jsonResponse({
        opening_id: '10000000-0000-4000-8000-000000000001',
        opening_codigo: 'AI-20260820-ABC',
        material_scm_id: 1,
        material_codigo: 'MP-PP-CLARIFICADO',
        material_nombre: 'PP clarificado',
        ubicacion_codigo: 'A-ENVA-MP-GEN',
        estado_calidad: 'LIBERADO',
        unidad_medida: 'KG',
        unidades_logisticas: [unit],
      }))
      .mockReturnValueOnce(jsonResponse({
        template_version: 'INVENTARIO_APERTURA_TSPL_1',
        preview_svg: '<svg xmlns="http://www.w3.org/2000/svg"/>',
      }))
      .mockReturnValueOnce(jsonResponse({
        template_version: 'INVENTARIO_APERTURA_TSPL_1',
        result: 'SIMULADA',
        simulated: true,
        preview_svg: '<svg xmlns="http://www.w3.org/2000/svg"/>',
      }));
    vi.stubGlobal('fetch', fetchMock);
    render(<ScmInventoryOpening peso={25.1} listening simulationEnabled onSimulateWeight={vi.fn()} />);

    const scanner = screen.getByPlaceholderText(/QR de apertura física/);
    fireEvent.change(scanner, { target: { value: JSON.stringify({
      type: 'SCM_INVENTORY_OPENING_TARGET', v: 1,
      opening_id: '10000000-0000-4000-8000-000000000001',
      material_scm_id: 1, ubicacion_codigo: 'A-ENVA-MP-GEN',
    }) } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('UL-EXISTENTE');

    fireEvent.click(screen.getByRole('button', { name: /Ver sticker UL-EXISTENTE/ }));
    const preview = await screen.findByAltText(/TSPL de la unidad UL-EXISTENTE/);
    expect(preview.getAttribute('src')).toContain('data:image/svg+xml');
    expect(screen.getByText(/109 × 50 mm · 203 DPI/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Imprimir sticker TSPL' }));
    expect(await screen.findByText(/simulaci.n local/i)).toBeTruthy();
    expect(fetchMock.mock.calls[2][0]).toContain('/labels/print');
    expect(fetchMock.mock.calls[2][1].headers['Idempotency-Key']).toBeTruthy();
  });

  it('resuelve cada bolsa origen sin confirmar todavía el aporte', async () => {
    const fetchMock = vi.fn().mockReturnValue(jsonResponse({
      id: '20000000-0000-4000-8000-000000000001',
      codigo: 'UL-ORIGEN1', qr_value: 'SCM:UL:ORIGEN1',
      material: { codigo: 'MP-PP-CLARIFICADO', nombre: 'PP clarificado' },
      ubicacion_codigo: 'A-ENVA-MP-GEN', cantidad_utilizable_kg: '25.000',
    }));
    vi.stubGlobal('fetch', fetchMock);
    render(<ScmPreparedMaterialWeighing peso={40.12} listening simulationEnabled onSimulateWeight={vi.fn()} />);

    const contextScanner = screen.getByPlaceholderText(/contexto QR de la OPM/);
    fireEvent.change(contextScanner, { target: { value: JSON.stringify({
      type: 'SCM_PREPARATION_WEIGHT_TARGET', v: 1,
      orden_preparacion_id: '30000000-0000-4000-8000-000000000001',
      orden_preparacion_codigo: 'OPM-000001', receta_nombre: 'Transparente',
      objetivo_kg: 40, tipo_uso: 'APORTE', pesado_por_id: 6,
    }) } });
    fireEvent.keyDown(contextScanner, { key: 'Enter' });
    const sourceScanner = await screen.findByLabelText(/Escanear bolsa de materia prima/);
    fireEvent.change(sourceScanner, { target: { value: 'SCM:UL:ORIGEN1' } });
    fireEvent.keyDown(sourceScanner, { key: 'Enter' });

    expect(await screen.findByText(/Bolsa UL-ORIGEN1 aceptada/)).toBeTruthy();
    expect(screen.getByText(/uso estimado 25.000 kg/)).toBeTruthy();
    expect(screen.getByText(/faltante estimado: 15.000 kg/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Confirmar pesaje (F2)' }).disabled).toBe(false);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });
});
