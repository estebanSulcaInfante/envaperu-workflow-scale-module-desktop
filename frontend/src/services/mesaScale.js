export const MESA_SCALE_STATUS_URL = '/api/mesa/balanza';
export const MESA_SCALE_CAPTURE_URL = '/api/mesa/balanza/capturas';

export const EMPTY_SCALE = Object.freeze({
  modo: null,
  disponible: false,
  base: null,
  kg: null,
  kg_en_vivo: null,
  estable: null,
  mensaje: '',
});

export function hasLiveScaleReading(value) {
  if (value == null || value === '') return false;
  const number = Number(String(value).replace(',', '.'));
  return Number.isFinite(number);
}

function normalizeScaleStatus(value) {
  const mode = value?.modo === 'manual' || value?.modo === 'accura' ? value.modo : null;
  const base = value?.base === 'NT' || value?.base === 'GS' ? value.base : null;
  return {
    modo: mode,
    disponible: value?.disponible === true,
    base,
    kg: value?.kg == null ? null : String(value.kg),
    kg_en_vivo: value?.kg_en_vivo == null
      ? (value?.kg == null ? null : String(value.kg))
      : String(value.kg_en_vivo),
    estable: typeof value?.estable === 'boolean' ? value.estable : null,
    mensaje: String(value?.mensaje || ''),
  };
}

async function readJsonResponse(response, fallbackMessage) {
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    const error = new Error(data.error || data.mensaje || fallbackMessage);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

export async function getMesaScaleStatus(fetcher = globalThis.fetch, options = {}) {
  let response;
  try {
    const request = options?.signal ? [MESA_SCALE_STATUS_URL, { signal: options.signal }] : [MESA_SCALE_STATUS_URL];
    response = await fetcher(...request);
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause;
    const error = new Error('No se pudo consultar la balanza de mesa.');
    error.kind = 'network';
    error.cause = cause;
    throw error;
  }
  return normalizeScaleStatus(await readJsonResponse(response, 'No se pudo consultar la balanza de mesa.'));
}

export async function captureMesaScale({
  codigo,
  token,
  operationId,
  fetcher = globalThis.fetch,
}) {
  const headers = { 'Content-Type': 'application/json' };
  if (operationId) headers['Idempotency-Key'] = operationId;
  let response;
  try {
    response = await fetcher(MESA_SCALE_CAPTURE_URL, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        codigo,
        ...(token ? { scale_token: token } : {}),
      }),
    });
  } catch (cause) {
    const error = new Error('No se pudo capturar la lectura de la balanza.');
    error.kind = 'network';
    error.cause = cause;
    throw error;
  }
  const data = await readJsonResponse(response, 'No se pudo capturar la lectura de la balanza.');
  const kg = data?.kg ?? data?.peso_kg ?? null;
  return {
    ...data,
    kg: kg == null ? null : String(kg),
    token: data?.scale_token || data?.token || data?.capture_token || token || null,
  };
}

export function scaleErrorMessage(error, fallback = 'No se pudo leer la balanza. Reintente con el mismo código.') {
  return error?.data?.mensaje || error?.data?.error || error?.message || fallback;
}
