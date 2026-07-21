const roundKg = (value) => Number(Number(value).toFixed(3));

export const calculateWeightAdjustment = (grossWeightKg, discountPercentageInput = 0) => {
  const grossWeight = Number(grossWeightKg);
  const discountPercentage = discountPercentageInput === ''
    ? 0
    : Number(discountPercentageInput);

  const valid = Number.isFinite(grossWeight)
    && grossWeight >= 0
    && Number.isFinite(discountPercentage)
    && discountPercentage >= 0
    && discountPercentage < 100;

  if (!valid) {
    return {
      valid: false,
      grossWeightKg: Number.isFinite(grossWeight) ? roundKg(grossWeight) : 0,
      discountPercentage,
      discountFraction: null,
      discountedWeightKg: null,
      attributableWeightKg: null,
    };
  }

  const discountFraction = discountPercentage / 100;
  const attributableWeightKg = roundKg(grossWeight * (1 - discountFraction));

  return {
    valid: true,
    grossWeightKg: roundKg(grossWeight),
    discountPercentage,
    discountFraction,
    discountedWeightKg: roundKg(grossWeight - attributableWeightKg),
    attributableWeightKg,
  };
};
