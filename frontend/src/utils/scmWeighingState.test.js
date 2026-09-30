import { describe, expect, it } from 'vitest';
import { getWeighingState } from './scmWeighingState';

const input = { context: { can_weigh: true, can_register_weight_control: true,
  manga: { peso_bruto_max_kg: '15' } }, centralAvailable: true, listening: true,
  peso: 10.1, tare: 0.1, net: 10, lastControlNet: 0, validPartialClose: true };

describe('estado visible y habilitación usan las mismas reglas', () => {
  it.each([
    [{ busy: true }, 'Operación en curso'],
    [{ result: {} }, 'Cierre registrado · manga cerrada'],
    [{ listening: false }, 'Balanza desconectada'],
    [{ peso: NaN }, 'Esperando peso neto válido'],
    [{ peso: Infinity }, 'Esperando peso neto válido'],
    [{ peso: 0.1 }, 'Esperando peso neto válido'],
    [{ lastControlNet: 10 }, 'Sin aumento desde el último control'],
    [{ lastControlNet: 10.1 }, 'Sin aumento desde el último control'],
    [{ lastControlNet: 10, net: 10.000000000002 }, 'Sin aumento desde el último control'],
    [{ context: { can_weigh: false, manga: { estado: 'RECIBIDA' } } }, 'Manga cerrada'],
    [{ context: { can_weigh: false, manga: { estado: 'NUEVO' } } }, 'Manga no habilitada para pesar'],
    [{ context: { ...input.context, can_weigh: false, can_register_weight_control: false } }, 'Manga no habilitada para pesar'],
    [{ context: { ...input.context, demo_only: true } }, 'Vista de demostración · sin registro'],
  ])('bloquea coherentemente %j', (overrides, title) => {
    const result = getWeighingState({ ...input, ...overrides });
    expect(result.ready).toBe(false);
    expect(result.title).toBe(title);
    expect(result.recovery).toBeTruthy();
  });

  it('no prohíbe trabajo PAUSADO si Central lo permite', () => {
    expect(getWeighingState({ ...input, context: { ...input.context,
      manga: { trabajo_color: { estado: 'PAUSADO' } } } }).ready).toBe(true);
  });
  it('explica el efecto de control y no lo convierte en relevo', () => {
    expect(getWeighingState({ ...input, controlOnly: true }).recovery)
      .toContain('sin cambiar maquinista ni OT');
  });
  it('exige seleccionar control si Central no admite cierre final', () => {
    const result = getWeighingState({
      ...input,
      context: { ...input.context, can_weigh: false },
      controlOnly: false,
    });
    expect(result.ready).toBe(false);
    expect(result.title).toBe('Seleccione control de peso para continuar');
  });
  it('usa cierre final como intención inicial cuando Central lo permite', () => {
    const result = getWeighingState({ ...input, controlOnly: false });
    expect(result.ready).toBe(true);
    expect(result.title).toBe('Listo para cierre final');
  });
  it('permite reintentar sin comunicar listo ni éxito falso tras un error', () => {
    const result = getWeighingState({ ...input, error: 'Conexión perdida' });
    expect(result.kind).toBe('error');
    expect(result.ready).toBe(true);
    expect(result.title).toBe('Último intento sin confirmar');
  });
  it('K11 permite lectura sobre el máximo planificado si el resto es válido', () => {
    const result = getWeighingState({
      ...input,
      context: { ...input.context, manga: { peso_bruto_max_kg: '11.045' } },
      peso: 13.5,
      tare: 0.045,
      net: 13.455,
    });
    expect(result.ready).toBe(true);
    expect(result.title).toBe('Listo para cierre final');
  });
  it('K8 bloquea una intención ya consumida aunque la manga siga abierta', () => {
    const result = getWeighingState({ ...input, scanConsumed: true, net: 12 });
    expect(result.ready).toBe(false);
    expect(result.title).toBe('Pesaje registrado · escanee el siguiente QR');
    expect(result.recovery).toContain('Retire la manga');
  });
});
