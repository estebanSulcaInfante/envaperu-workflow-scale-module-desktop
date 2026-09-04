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
  can_register_weight_control: true,
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
    peso_fabricado_teorico_kg: '6.700',
    tara_nominal_kg: '0.100',
    imagen_url: 'https://central.example/api/piezas-color/PC-000001/imagen',
  },
};


describe('ScmWeighing', () => {
  beforeEach(() => vi.clearAllMocks());

  it('K9-01 usa cierre final por defecto y reserva el checkbox para controles', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);

    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });

    expect(await screen.findByText('Listo para cierre final')).toBeTruthy();
    expect(screen.getByLabelText('Solo control de peso').checked).toBe(false);
    fireEvent.keyDown(window, { key: 'F2' });

    expect(await screen.findByRole('dialog', { name: 'Confirmar cierre final' })).toBeTruthy();
    expect(scmWeighingApi.control).not.toHaveBeenCalled();
    expect(scmWeighingApi.confirm).not.toHaveBeenCalled();
  });

  it('K9-02 registra Control de peso solo cuando el operador lo selecciona', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    scmWeighingApi.control.mockResolvedValue({
      data: {
        control: {
          public_id: '20000000-0000-4000-8000-000000000007',
          tipo: 'AVANCE_KG',
          peso_neto_kg: '10.000',
          aporte_desde_control_anterior_kg: '10.000',
        },
        manga: { estado: 'EN_LLENADO' },
        print_result: { result: 'IMPRESA' },
      },
    });
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);

    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });

    expect(await screen.findByText('Listo para cierre final')).toBeTruthy();
    expect(screen.getByLabelText('Solo control de peso').checked).toBe(false);
    fireEvent.click(screen.getByLabelText('Solo control de peso'));
    expect(screen.getByText('Listo para control de peso')).toBeTruthy();
    fireEvent.keyDown(window, { key: 'F2' });

    await waitFor(() => expect(scmWeighingApi.control).toHaveBeenCalledTimes(1));
    expect(scmWeighingApi.confirm).not.toHaveBeenCalled();
  });

  it('K7-02 protege el cierre con confirmación y cancelación segura', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);

    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('Listo para cierre final');
    fireEvent.keyDown(window, { key: 'F2' });

    const dialog = await screen.findByRole('dialog', { name: 'Confirmar cierre final' });
    expect(dialog.textContent).toContain('OP0084-OT001-M001');
    expect(dialog.textContent).toContain('10.000 kg');
    expect(scmWeighingApi.confirm).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole('button', {
      name: 'Cancelar; revisar intención',
    }));

    fireEvent.keyDown(window, { key: 'F2', repeat: true });
    expect(scmWeighingApi.confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar; revisar intención' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByLabelText('Solo control de peso').checked).toBe(false);
    expect(screen.getByText('Listo para cierre final')).toBeTruthy();
  });

  it('K9-03 Escape cancela el diálogo y conserva el cierre como intención inicial', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);

    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('Listo para cierre final');
    fireEvent.keyDown(window, { key: 'F2' });
    await screen.findByRole('dialog', { name: 'Confirmar cierre final' });
    fireEvent.keyDown(window, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByLabelText('Solo control de peso').checked).toBe(false);
    expect(screen.getByText('Listo para cierre final')).toBeTruthy();
    expect(scmWeighingApi.confirm).not.toHaveBeenCalled();
  });

  it('K9-06 deja listo el cierre cuando el contexto no admite controles', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: {
      ...context,
      can_register_weight_control: false,
      manga: {
        ...context.manga,
        tipo: 'ARMADO',
        codigo: 'OA000321-OT777-M001',
        cantidad_fuente: 'RESPONSABLE_ARMADO',
      },
    } });
    scmWeighingApi.confirm.mockResolvedValue({
      data: {
        confirmed: { weighing: { estado_manga: 'PESADA' } },
        print_result: { result: 'IMPRESA' },
      },
    });
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);

    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr-armado' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });

    expect(await screen.findByText('Listo para cierre final')).toBeTruthy();
    expect(screen.getByLabelText('Solo control de peso').disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Pesar manga (F2)' }).disabled).toBe(false);
    fireEvent.keyDown(window, { key: 'F2' });
    await screen.findByRole('dialog', { name: 'Confirmar cierre final' });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar cierre de manga' }));

    await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(1));
  });

  it.each([
    ['PESADA', 'Manga cerrada', 'Escanee otra manga. Si el cierre fue incorrecto, solicite revisión en Central.'],
    ['PREETIQUETADA', 'Trabajo de la OT sin iniciar', 'Solicite a Central iniciar el Trabajo de la OT y vuelva a escanear.'],
  ])('explica el bloqueo %s junto al único botón sin permitir F2', async (estado, mensaje, recuperacion) => {
    scmWeighingApi.resolve.mockResolvedValue({ data: {
      ...context, can_weigh: false, can_register_weight_control: false,
      manga: { ...context.manga, estado },
      bloqueos_pesaje: { completar_final: { codigo: 'BLOQUEO', mensaje, recuperacion, responsable: 'CENTRAL' } },
    } });
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('QR de manga SCM'), { target: { value: 'qr' } });
    fireEvent.keyDown(screen.getByLabelText('QR de manga SCM'), { key: 'Enter' });
    expect(await screen.findByText(mensaje)).toBeTruthy();
    expect(screen.getByText(recuperacion)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Pesar manga (F2)' }).disabled).toBe(true);
    fireEvent.keyDown(window, { key: 'F2' });
    expect(scmWeighingApi.confirm).not.toHaveBeenCalled();
    expect(scmWeighingApi.control).not.toHaveBeenCalled();
  });

  it('conserva último control del servidor al reescanear y cambiar intención', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: {
      ...context, continuidad: { ultimo_control: { peso_neto_kg: '10.000' } },
    } });
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('OP0084-OT001-M001');
    expect(screen.getByRole('button', { name: 'Pesar manga (F2)' }).disabled).toBe(true);
    const mode = screen.getByLabelText('Solo control de peso');
    fireEvent.click(mode);
    expect(screen.getByText('Sin aumento desde el último control')).toBeTruthy();
    fireEvent.click(mode);
    expect(screen.getByRole('button', { name: 'Pesar manga (F2)' }).disabled).toBe(true);
  });

  it('presenta transparente como patrón cuadriculado y conserva su nombre visible', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: {
      ...context,
      manga: {
        ...context.manga,
        pieza_color: 'Jarra Real 6 L Transparente (PC-000777)',
        color: 'TRANSPARENTE',
        color_hex: '#EAF7F7',
        color_identidad: {
          id: 7,
          nombre: 'TRANSPARENTE',
          base: { id: 4, nombre: 'TRANSPARENTE' },
          familia: { id: 3, nombre: 'TRANSPARENTE' },
          hex: '#EAF7F7',
        },
      },
    } });

    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr-transparente' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });

    expect(await screen.findByText('Identidad del contenido')).toBeTruthy();
    expect(screen.getByText('Jarra Real 6 L Transparente (PC-000777)')).toBeTruthy();
    expect(screen.getByText('TRANSPARENTE', { selector: '.scm-color-identity b' })).toBeTruthy();
    expect(screen.getByLabelText('Muestra de color transparente').classList)
      .toContain('transparent');
  });

  it('usa el hex maestro para la muestra de un color sólido', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: {
      ...context,
      manga: {
        ...context.manga,
        color_hex: '#E91E63',
        color_identidad: {
          id: 8,
          nombre: 'FUCSIA SÓLIDO',
          base: { id: 5, nombre: 'FUCSIA' },
          familia: { id: 2, nombre: 'SÓLIDO' },
          hex: '#E91E63',
        },
      },
    } });

    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr-fucsia' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });

    const swatch = await screen.findByLabelText('Muestra de color FUCSIA SÓLIDO');
    expect(swatch.classList).toContain('solid');
    expect(swatch.style.getPropertyValue('--scm-color-swatch')).toBe('#E91E63');
  });

  it('limpia el anuncio anterior si el siguiente QR es rechazado', async () => {
    scmWeighingApi.resolve.mockResolvedValueOnce({ data: context })
      .mockRejectedValueOnce({ response: { data: { message: 'Etiqueta invalidada' } } });
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr1' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('OP0084-OT001-M001');
    fireEvent.change(scanner, { target: { value: 'qr2' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('Etiqueta invalidada');
    expect(screen.queryByText('OP0084-OT001-M001')).toBeNull();
    expect(screen.getByRole('status').textContent).not.toContain('Manga activa');
    expect(screen.getByRole('button', { name: 'Pesar manga (F2)' }).disabled).toBe(true);
  });

  it('un F2 repetido durante el envío no duplica el llamado y muestra espera', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    let finish;
    scmWeighingApi.control.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('OP0084-OT001-M001');
    fireEvent.click(screen.getByLabelText('Solo control de peso'));
    fireEvent.keyDown(window, { key: 'F2' });
    fireEvent.keyDown(window, { key: 'F2', repeat: true });
    expect(scmWeighingApi.control).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Operación en curso')).toBeTruthy();
    expect(screen.getByLabelText('Solo control de peso').disabled).toBe(true);
    finish({ data: {
      control: { peso_neto_kg: '10.000', aporte_desde_control_anterior_kg: '10.000' },
      manga: { estado: 'EN_LLENADO' },
      print_result: { result: 'PENDIENTE' },
    } });
    expect(await screen.findByText('Avance en kg registrado')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Pesar manga (F2)' }).disabled).toBe(true);
  });

  it('tras respuesta incierta conserva el modo y la misma operación para reintentar', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    scmWeighingApi.control.mockRejectedValue({ response: { data: { message: 'Respuesta perdida' } } });
    render(<ScmWeighing peso={10.1} listening centralState="ONLINE" onConnect={vi.fn()} />);
    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'qr' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await screen.findByText('OP0084-OT001-M001');
    fireEvent.click(screen.getByLabelText('Solo control de peso'));
    fireEvent.keyDown(window, { key: 'F2' });
    await screen.findByText('Último intento sin confirmar');
    expect(screen.getByLabelText('Solo control de peso').disabled).toBe(true);
    fireEvent.keyDown(window, { key: 'F2' });
    await waitFor(() => expect(scmWeighingApi.control).toHaveBeenCalledTimes(2));
    expect(scmWeighingApi.control.mock.calls[0]).toEqual(scmWeighingApi.control.mock.calls[1]);
    expect(scmWeighingApi.confirm).not.toHaveBeenCalled();
  });

  it('resuelve QR y confirma el cierre explícito sin pedir datos al maquinista', async () => {
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
    expect(screen.getAllByText('10.000 kg').length).toBeGreaterThan(0);
    fireEvent.keyDown(window, { key: 'F2' });
    await screen.findByRole('dialog', { name: 'Confirmar cierre final' });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar cierre de manga' }));

    await waitFor(() => {
      expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText('Pesaje central confirmado')).toBeTruthy();
    expect(screen.getByText('Etiqueta final: IMPRESA')).toBeTruthy();
    expect(screen.queryByText('Cantidad final 50.000 un')).toBeNull();
    expect(screen.queryByText('Jose Quispe · OT-000001: 20.000 un')).toBeNull();
    expect(screen.queryByText('Pedro Ramos · OT-000002: 30.000 un')).toBeNull();
    expect(screen.getByText(/Peso fabricado teórico 10.000 kg/i)).toBeTruthy();
    expect(screen.queryByRole('button', {
      name: 'Registrar corte de turno — continúa abierta',
    })).toBeNull();
    expect(screen.queryByLabelText(/Operador/)).toBeNull();
    expect(screen.queryByLabelText(/Peso bruto/)).toBeNull();
  });

  it('anuncia de forma visible cuando un nuevo QR cambia la manga activa', async () => {
    scmWeighingApi.resolve
      .mockResolvedValueOnce({ data: context })
      .mockResolvedValueOnce({
        data: {
          ...context,
          scanned_label_id: '10000000-0000-4000-8000-000000000002',
          manga: {
            ...context.manga,
            codigo: 'OP0084-OT001-M002',
            imagen_url: null,
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

    const scanner = screen.getByLabelText('QR de manga SCM');
    fireEvent.change(scanner, { target: { value: 'primer-qr' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain(
      'QR leído. Manga seleccionada: OP0084-OT001-M001',
    ));

    fireEvent.change(scanner, { target: { value: 'segundo-qr' } });
    fireEvent.keyDown(scanner, { key: 'Enter' });

    await waitFor(() => expect(screen.getByRole('status').textContent).toContain(
      'Cambio de manga confirmado: OP0084-OT001-M001 → OP0084-OT001-M002',
    ));
    expect(screen.getByText('OP0084-OT001-M002', { selector: 'strong' })).toBeTruthy();
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
      name: 'Pesar manga (F2)',
    }).disabled).toBe(true);
  });

  it('no ofrece corte de turno cuando central solo autoriza pesaje final', async () => {
    scmWeighingApi.resolve.mockResolvedValue({
      data: {
        ...context,
        can_register_shift_cut: false,
        can_register_weight_control: false,
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

    expect(await screen.findByText('OP0084-OT001-M001')).toBeTruthy();
    expect(screen.queryByRole('button', {
      name: 'Registrar corte de turno — continúa abierta',
    })).toBeNull();
    expect(screen.getByText('Listo para cierre final')).toBeTruthy();
    expect(screen.getByRole('button', {
      name: 'Pesar manga (F2)',
    }).disabled).toBe(false);
  });

  it('presenta el pesaje de Armado como neto total y no como produccion de fabricacion', async () => {
    scmWeighingApi.resolve.mockResolvedValue({
      data: {
        ...context,
        can_register_shift_cut: false,
        can_register_weight_control: false,
        manga: {
          ...context.manga,
          codigo: 'OA000321-OT777-M001',
          op_ot: undefined,
          oa_ot: 'OA-000321 - OT-000777',
          cantidad_fuente: 'RESPONSABLE_ARMADO',
          articulo_clase: 'SUBENSAMBLE_WIP',
          articulo_codigo: 'WIP-ORG5-ARMADA-PLOMO',
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

    fireEvent.keyDown(window, { key: 'F2' });
    await screen.findByRole('dialog', { name: 'Confirmar cierre final' });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar cierre de manga' }));

    expect(await screen.findByText('Pesaje central confirmado')).toBeTruthy();
    expect(screen.getByText(
      'WIP · WIP-ORG5-ARMADA-PLOMO · BASE ORG. #5 ARMADA - ASAS PLOMO',
    )).toBeTruthy();
    expect(screen.getByText('Neto total de Armado 20.300 kg')).toBeTruthy();
    expect(screen.queryByText(/Producción OT/)).toBeNull();
  });

  it('identifica de forma dominante una salida de Producto terminado', async () => {
    scmWeighingApi.resolve.mockResolvedValue({
      data: {
        ...context,
        can_register_shift_cut: false,
        can_register_weight_control: false,
        manga: {
          ...context.manga,
          codigo: 'OA000322-OT778-M001',
          op_ot: undefined,
          oa_ot: 'OA-000322 - OT-000778',
          cantidad_fuente: 'RESPONSABLE_ARMADO',
          articulo_clase: 'PRODUCTO_TERMINADO',
          articulo_codigo: 'PT-000120',
          pieza_color: 'Jarra grande armada',
        },
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

    expect(await screen.findByText(
      'Producto terminado · PT-000120 · Jarra grande armada',
    )).toBeTruthy();
    expect(screen.getByText('Peso neto total de Armado (kg)')).toBeTruthy();
    expect(screen.queryByText(/peso de tapas|peso de picos/i)).toBeNull();
  });

  it('K8-01 consume el QR tras un control y exige reescanear aun si cambia el peso', async () => {
    scmWeighingApi.resolve
      .mockResolvedValueOnce({ data: context })
      .mockResolvedValueOnce({ data: {
        ...context,
        continuidad: {
          ultimo_control: { peso_neto_kg: '3.700' },
          ultima_referencia_peso: {
            fuente: 'CONTROL_PESO',
            peso_neto_kg: '3.700',
          },
        },
      } });
    scmWeighingApi.control.mockResolvedValue({
      data: {
        control: {
          public_id: '20000000-0000-4000-8000-000000000001',
          conteo_acumulado_un: null,
          tipo: 'AVANCE_KG',
          peso_neto_kg: '3.700',
          aporte_desde_control_anterior_kg: '1.500',
        },
        manga: { estado: 'EN_LLENADO' },
        produccion_confirmada_un: '0',
        inventario_creado: false,
        print_job_id: '30000000-0000-4000-8000-000000000001',
        print_result: { result: 'IMPRESA' },
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
    const { rerender } = render(
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

    expect(screen.getByRole('img', { name: 'Pieza de la manga activa' }).getAttribute('src'))
      .toBe(context.manga.imagen_url);
    expect(screen.getByText('MANGA SELECCIONADA')).toBeTruthy();
    expect(screen.getByText('OP0084-OT001-M001', { selector: 'strong' })).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Solo control de peso'));
    fireEvent.click(screen.getByRole('button', { name: 'Pesar manga (F2)' }));

    await waitFor(() => expect(scmWeighingApi.control).toHaveBeenCalledWith(
      context.scanned_label_id,
      expect.any(String),
    ));
    expect(scmWeighingApi.confirm).not.toHaveBeenCalled();
    expect(await screen.findByText('Avance en kg registrado')).toBeTruthy();
    expect(screen.getByText(/Peso neto real 3.700 kg · aporte desde control anterior 1.500 kg/i)).toBeTruthy();
    expect(screen.getByText(/QR de preetiqueta preservado · sin conteo · impresión IMPRESA/i)).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByLabelText('QR de manga SCM'));
    expect(screen.queryByLabelText('Conteo acumulado de unidades')).toBeNull();
    expect(screen.getByRole('button', { name: 'Pesar manga (F2)' }).disabled).toBe(true);
    expect(screen.getByText('Pesaje registrado · escanee el siguiente QR')).toBeTruthy();
    expect(screen.queryByText('-0.000 kg')).toBeNull();

    rerender(
      <ScmWeighing
        peso={4.0}
        listening
        centralState="ONLINE"
        onConnect={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Pesar manga (F2)' }).disabled).toBe(true);
    fireEvent.keyDown(window, { key: 'F2' });
    expect(scmWeighingApi.control).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText('QR de manga SCM'), {
      target: { value: '{"v":1,"label_id":"same-label"}' },
    });
    fireEvent.keyDown(screen.getByLabelText('QR de manga SCM'), { key: 'Enter' });
    await waitFor(() => expect(scmWeighingApi.resolve).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('button', { name: 'Pesar manga (F2)' }).disabled).toBe(false);

    fireEvent.keyDown(window, { key: 'F2' });
    await screen.findByRole('dialog', { name: 'Confirmar cierre final' });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar cierre de manga' }));
    await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledTimes(1));
  });

  it('K8-05 no solicita unidades reales para cerrar una manga simple de Fabricación', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: context });
    scmWeighingApi.confirm.mockResolvedValue({
      data: {
        confirmed: {
          weighing: {
            estado_manga: 'PESADA',
            peso_fisico_neto_kg: '3.700',
            kg_produccion_ot: '3.700',
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

    expect(screen.queryByLabelText('Cierre final parcial — no continuará abierta')).toBeNull();
    expect(screen.queryByLabelText('Unidades reales de la manga incompleta')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Pesar manga (F2)' }));
    await screen.findByRole('dialog', { name: 'Confirmar cierre final' });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar cierre de manga' }));

    await waitFor(() => expect(scmWeighingApi.confirm).toHaveBeenCalledWith(
      context.scanned_label_id,
      expect.any(String),
      {},
    ));
    expect(screen.queryByText(/Saldo devuelto al plan/i)).toBeNull();
  });

  it('K8-05 presenta el contexto de Fabricación en kg y no como conteo de unidades', async () => {
    scmWeighingApi.resolve.mockResolvedValue({ data: {
      ...context,
      continuidad: {
        ultima_referencia_peso: {
          fuente: 'CONTROL_PESO',
          peso_neto_kg: '4.790',
        },
      },
    } });
    render(<ScmWeighing peso={5.07} listening centralState="ONLINE" onConnect={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('QR de manga SCM'), { target: { value: 'qr' } });
    fireEvent.keyDown(screen.getByLabelText('QR de manga SCM'), { key: 'Enter' });

    expect(await screen.findByText('Peso fabricado teórico')).toBeTruthy();
    expect(screen.getByText('6.700 kg')).toBeTruthy();
    expect(screen.getByText('Último NET aceptado')).toBeTruthy();
    expect(screen.getByText('4.790 kg')).toBeTruthy();
    expect(screen.getByText('Diferencia')).toBeTruthy();
    expect(screen.getByText('0.180 kg')).toBeTruthy();
    expect(screen.queryByText('Cantidad teórica del plan')).toBeNull();
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
      name: 'Pesar manga (F2)',
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
    fireEvent.click(screen.getByRole('button', { name: 'Pesar manga (F2)' }));
    await screen.findByRole('dialog', { name: 'Confirmar cierre final' });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar cierre de manga' }));

    expect(await screen.findByText('Pesaje demo confirmado')).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Etiqueta TSC final simulada' })).toBeTruthy();
    expect(screen.getByText('Salida TSC simulada // POSTPESAJE')).toBeTruthy();
  });
});
