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
  can_register_shift_cut: true,
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
            cantidad_confirmada: '50.000',
          },
          atribucion_turnos: [
            {
              id: 'tramo-jose',
              maquinista: 'Jose Quispe',
              ot_codigo: 'OT-000001',
              cantidad_atribuida_un: '20.000',
            },
            {
              id: 'tramo-pedro',
              maquinista: 'Pedro Ramos',
              ot_codigo: 'OT-000002',
              cantidad_atribuida_un: '30.000',
            },
          ],
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
    expect(screen.getByText('Cantidad final 50.000 un')).toBeTruthy();
    expect(screen.getByText('Jose Quispe · OT-000001: 20.000 un')).toBeTruthy();
    expect(screen.getByText('Pedro Ramos · OT-000002: 30.000 un')).toBeTruthy();
    expect(screen.queryByRole('button', {
      name: 'Registrar corte de turno — continúa abierta',
    })).toBeNull();
    expect(screen.queryByLabelText(/Operador/)).toBeNull();
    expect(screen.queryByLabelText(/Peso bruto/)).toBeNull();
  });

  it('presenta el pesaje de Armado como neto total y no como produccion de fabricacion', async () => {
    scmWeighingApi.resolve.mockResolvedValue({
      data: {
        ...context,
        can_register_shift_cut: false,
        manga: {
          ...context.manga,
          codigo: 'OA000321-OT777-M001',
          op_ot: undefined,
          oa_ot: 'OA-000321 - OT-000777',
          cantidad_fuente: 'RESPONSABLE_ARMADO',
          pieza_color: 'BASE ORG. #5 ARMADA - ASAS PLOMO',
        },
      },
    });
    scmWeighingApi.confirm.mockResolvedValue({
      data: {
        confirmed: {
          weighing: {
            estado_manga: 'PESADA',
            peso_fisico_neto_kg: '20.300',
            kg_produccion_ot: '20.000',
            cantidad_confirmada: '100.000',
          },
        },
        print_result: { result: 'IMPRESA' },
      },
    });
    render(
      <ScmWeighing
        peso={20.4}
        listening
        centralState="ONLINE"
        onConnect={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('QR de manga SCM'), {
      target: { value: '{"v":1,"type":"SCM_MANGA_LABEL"}' },
    });
    fireEvent.keyDown(screen.getByLabelText('QR de manga SCM'), { key: 'Enter' });
    await screen.findByText('OA000321-OT777-M001');

    expect(screen.getByText('Artículo armado')).toBeTruthy();
    expect(screen.getByText('Cantidad confirmada por Armado')).toBeTruthy();
    expect(screen.getByText('Neto total de Armado')).toBeTruthy();

    fireEvent.keyDown(window, { key: 'F2' });

    expect(await screen.findByText('Pesaje central confirmado')).toBeTruthy();
    expect(screen.getByText('Neto total de Armado 20.300 kg')).toBeTruthy();
    expect(screen.queryByText(/Producción OT/)).toBeNull();
  });

  it('reanuda el acuse pendiente de F2 sin presentar una reimpresión', async () => {
    const confirmed = {
      weighing: {
        estado_manga: 'PESADA',
        peso_fisico_neto_kg: '10.000',
        kg_produccion_ot: '10.000',
      },
    };
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    scmWeighingApi.confirm
      .mockResolvedValueOnce({
        data: {
          confirmed,
          print_result: {
            result: 'IMPRESA',
            ack_pending: true,
          },
        },
      })
      .mockResolvedValueOnce({
        data: {
          confirmed,
          print_result: {
            result: 'IMPRESA',
            ack_pending: false,
            ack_recovered: true,
            already_printed: true,
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
    fireEvent.keyDown(screen.getByLabelText('QR de manga SCM'), { key: 'Enter' });
    await screen.findByText('OP0084-OT001-M001');
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar pesaje (F2)' }));

    const resume = await screen.findByRole('button', {
      name: 'Reanudar acuse central',
    });
    expect(screen.getByText(/sticker aceptado; acuse central pendiente/i)).toBeTruthy();
    fireEvent.click(resume);

    await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(2));
    const firstCall = scmWeighingApi.confirm.mock.calls[0];
    const secondCall = scmWeighingApi.confirm.mock.calls[1];
    expect(secondCall).toEqual(firstCall);
    expect(await screen.findByText(/sin volver a imprimir el sticker/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Reanudar acuse central' })).toBeNull();
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

  it('no ofrece corte de turno cuando central solo autoriza pesaje final', async () => {
    scmWeighingApi.resolve.mockResolvedValue({
      data: { ...context, can_register_shift_cut: false },
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
    fireEvent.keyDown(screen.getByLabelText('QR de manga SCM'), { key: 'Enter' });

    expect(await screen.findByText('OP0084-OT001-M001')).toBeTruthy();
    expect(screen.queryByRole('button', {
      name: 'Registrar corte de turno — continúa abierta',
    })).toBeNull();
    expect(screen.getByRole('button', {
      name: 'Confirmar pesaje (F2)',
    }).disabled).toBe(false);
  });

  it('registra un corte acumulado sin cerrar ni imprimir y conserva F2 como cierre final', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    scmWeighingApi.control.mockResolvedValue({
      data: {
        control: {
          public_id: '20000000-0000-4000-8000-000000000001',
          conteo_acumulado_un: '37',
          peso_fisico_neto_kg: '3.700',
        },
        manga: { estado: 'ABIERTA' },
        produccion_confirmada_un: '0',
        inventario_creado: false,
        print_job_id: null,
        qr_preservado: true,
      },
    });
    scmWeighingApi.confirm.mockResolvedValue({
      data: {
        confirmed: {
          weighing: {
            estado_manga: 'PESADA',
            peso_fisico_neto_kg: '3.700',
            kg_produccion_ot: '10.000',
          },
        },
        print_result: { result: 'IMPRESA' },
      },
    });
    render(
      <ScmWeighing
        peso={3.8}
        listening
        centralState="ONLINE"
        onConnect={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('QR de manga SCM'), {
      target: { value: '{"v":1,"type":"SCM_MANGA_LABEL"}' },
    });
    fireEvent.keyDown(screen.getByLabelText('QR de manga SCM'), { key: 'Enter' });
    await screen.findByText('OP0084-OT001-M001');

    fireEvent.change(screen.getByLabelText('Conteo acumulado de unidades'), {
      target: { value: '37' },
    });
    fireEvent.change(screen.getByLabelText('Motivo del corte de turno'), {
      target: { value: 'RELEVO_TURNO' },
    });
    fireEvent.click(screen.getByRole('button', {
      name: 'Registrar corte de turno — continúa abierta',
    }));

    await waitFor(() => expect(scmWeighingApi.control).toHaveBeenCalledWith(
      context.scanned_label_id,
      expect.any(String),
      '37',
      'RELEVO_TURNO',
    ));
    expect(scmWeighingApi.confirm).not.toHaveBeenCalled();
    expect(await screen.findByText('Control de turno registrado')).toBeTruthy();
    expect(screen.getByText(/QR preservado · producción confirmada 0/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Confirmar pesaje (F2)' }).disabled).toBe(true);

    fireEvent.keyDown(window, { key: 'F2' });
    expect(scmWeighingApi.confirm).not.toHaveBeenCalled();
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
