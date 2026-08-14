import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { scmWeighingApi } from '../services/api';
import ScmWeighing from './ScmWeighing';


vi.mock('../services/api', () => ({
  scmWeighingApi: {
    resolve: vi.fn(),
    confirm: vi.fn(),
  },
}));

const context = {
  can_weigh: true,
  scanned_label_id: '10000000-0000-4000-8000-000000000001',
  manga: {
    codigo: 'OP0084-OT001-M001',
    op_ot: 'OP0084 - OT-000001',
    ot: {
      codigo: 'OT-000001',
      maquina: 'Haitian 3000',
      turno: 'DIA',
    },
    trabajo_color: {
      codigo: 'TC-000001',
      estado: 'EN_EJECUCION',
      orden_fabricacion: 'OF-000042',
      corrida: 'OF-000042-C01',
      color: 'FUCSIA',
    },
    asignacion_vigente: {
      maquinista: 'Juan Perez',
    },
    fecha_operativa: '2026-07-28',
    maquinista: 'Juan Perez',
    pieza_color: 'Asa fucsia (PC-000001)',
    color: 'FUCSIA',
    tipo: 'NORMAL',
    cantidad_asignada_un: '100',
    tara_nominal_kg: '0.100',
  },
};


describe('ScmWeighing', () => {
  beforeEach(() => vi.clearAllMocks());

  it('resuelve QR y F2 confirma sin pedir datos al maquinista', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    scmWeighingApi.confirm.mockResolvedValue({
      data: {
        confirmed: {
          weighing: {
            estado_manga: 'PESADA',
            peso_fisico_neto_kg: '10.000',
            kg_produccion_ot: '10.000',
          },
        },
        print_result: { result: 'IMPRESA' },
      },
    });
    render(
      <ScmWeighing
        peso={10.1}
        listening
        centralState="ONLINE"
        onConnect={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('QR de manga SCM'), {
      target: { value: '{"v":1,"type":"SCM_MANGA_LABEL"}' },
    });
    fireEvent.keyDown(screen.getByLabelText('QR de manga SCM'), {
      key: 'Enter',
    });

    expect(await screen.findByText('OP0084-OT001-M001')).toBeTruthy();
    const currentWeight = screen.getByTestId('scm-current-weight');
    expect(currentWeight.getAttribute('aria-label')).toBe(
      'Peso actual de balanza: 10.100 kilogramos',
    );
    expect(currentWeight.textContent).toContain('10.100');
    expect(currentWeight.textContent).toContain('kg');
    expect(screen.getByText('OT-000001 · Haitian 3000 · DIA')).toBeTruthy();
    expect(screen.getByText('TC-000001 · FUCSIA')).toBeTruthy();
    expect(screen.getByText('OF-000042 · OF-000042-C01')).toBeTruthy();
    expect(screen.getByText('10.000 kg')).toBeTruthy();
    fireEvent.keyDown(window, { key: 'F2' });

    await waitFor(() => {
      expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText('Pesaje central confirmado')).toBeTruthy();
    expect(screen.getByText('Etiqueta final: IMPRESA')).toBeTruthy();
    expect(screen.queryByLabelText(/Operador/)).toBeNull();
    expect(screen.queryByLabelText(/Peso bruto/)).toBeNull();
  });

  it('bloquea F2 cuando central no esta en linea', () => {
    render(
      <ScmWeighing
        peso={10.1}
        listening
        centralState="CENTRAL_UNREACHABLE"
        onConnect={vi.fn()}
      />,
    );
    expect(
      screen.getByText('Piloto SCM bloqueado: central sin conexión'),
    ).toBeTruthy();
    expect(screen.getByRole('button', {
      name: 'Confirmar pesaje (F2)',
    }).disabled).toBe(true);
  });

  it('permite inyectar un peso manual cuando la estación local habilita simulación', async () => {
    const onSimulateWeight = vi.fn().mockResolvedValue({ peso_kg: 12.345 });
    render(
      <ScmWeighing
        peso={0}
        listening={false}
        centralState="ONLINE"
        onConnect={vi.fn()}
        simulationEnabled
        onSimulateWeight={onSimulateWeight}
      />,
    );

    fireEvent.change(screen.getByLabelText('Peso simulado en kilogramos'), {
      target: { value: '12.345' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Aplicar peso simulado' }));

    await waitFor(() => expect(onSimulateWeight).toHaveBeenCalledWith(12.345));
    expect(screen.getByText(/Modo local · balanza simulada/)).toBeTruthy();
  });

  it('mantiene compatible el contexto legacy sin Trabajo de color', async () => {
    scmWeighingApi.resolve.mockResolvedValue({
      data: {
        ...context,
        manga: {
          ...context.manga,
          ot: undefined,
          trabajo_color: undefined,
          asignacion_vigente: undefined,
        },
      },
    });
    render(
      <ScmWeighing
        peso={10.1}
        listening
        centralState="ONLINE"
        onConnect={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('QR de manga SCM'), {
      target: { value: '{"v":1,"type":"SCM_MANGA_LABEL"}' },
    });
    fireEvent.keyDown(screen.getByLabelText('QR de manga SCM'), {
      key: 'Enter',
    });

    expect(await screen.findByText('OP0084 - OT-000001')).toBeTruthy();
    expect(screen.queryByText('Trabajo de color')).toBeNull();
    expect(screen.getByRole('button', {
      name: 'Confirmar pesaje (F2)',
    }).disabled).toBe(false);
  });

  it('ofrece un recorrido directo y muestra la etiqueta final en la demo publica', async () => {
    scmWeighingApi.resolve.mockResolvedValue({
      data: { ...context, portfolio_demo: true },
    });
    scmWeighingApi.confirm.mockResolvedValue({
      data: {
        portfolio_demo: true,
        confirmed: {
          weighing: {
            estado_manga: 'PESADA',
            peso_fisico_neto_kg: '8.375',
            kg_produccion_ot: '8.375',
          },
        },
        print_result: {
          result: 'IMPRESA',
          simulated: true,
          preview_svg: '<svg viewBox="0 0 872 400"></svg>',
        },
      },
    });
    render(
      <ScmWeighing
        peso={8.475}
        listening
        centralState="PORTFOLIO_DEMO"
        onConnect={vi.fn()}
        simulationEnabled
        onSimulateWeight={vi.fn()}
        portfolioDemoMode
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Cargar manga demo' }));
    expect(await screen.findByText('OP0084-OT001-M001')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar pesaje (F2)' }));

    expect(await screen.findByText('Pesaje demo confirmado')).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Etiqueta TSC final simulada' })).toBeTruthy();
    expect(screen.getByText('Salida TSC simulada // POSTPESAJE')).toBeTruthy();
  });
});
