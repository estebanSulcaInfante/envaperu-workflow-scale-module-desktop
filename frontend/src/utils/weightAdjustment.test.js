import { describe, expect, it } from 'vitest';
import { calculateWeightAdjustment } from './weightAdjustment';

describe('calculateWeightAdjustment', () => {
  it('conserva el peso completo cuando el descuento es cero', () => {
    expect(calculateWeightAdjustment(30, 0)).toEqual({
      valid: true,
      grossWeightKg: 30,
      discountPercentage: 0,
      discountFraction: 0,
      discountedWeightKg: 0,
      attributableWeightKg: 30,
    });
  });

  it('descuenta el porcentaje ajeno a la pieza y redondea a tres decimales', () => {
    expect(calculateWeightAdjustment(8.2, 12.5)).toEqual({
      valid: true,
      grossWeightKg: 8.2,
      discountPercentage: 12.5,
      discountFraction: 0.125,
      discountedWeightKg: 1.025,
      attributableWeightKg: 7.175,
    });
  });

  it('interpreta un campo vacío como el descuento por defecto de cero', () => {
    expect(calculateWeightAdjustment(25, '').attributableWeightKg).toBe(25);
  });

  it.each([-1, 100, 120, 'no-numero'])(
    'rechaza el porcentaje inválido %s',
    (discount) => {
      expect(calculateWeightAdjustment(25, discount).valid).toBe(false);
    },
  );
});
