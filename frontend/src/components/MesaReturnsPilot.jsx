import { useEffect, useMemo, useRef, useState } from 'react';
import './MesaReturnsPilot.css';
import { MesaNotices, useMesaNotices } from './MesaNotices';
import {
  captureMesaScale,
  getMesaScaleStatus,
  scaleErrorMessage,
} from '../services/mesaScale';

const STATE_URL = '/api/mesa/state';
const PENDING_KEY = 'mesa-returns-pilot.pending-union';
const MODE_KEY = 'mesa-returns-pilot.mode';
const REQUEST_KEY = 'mesa-returns-pilot.receive-request-ids';
const ORIGINS_KEY = 'mesa-returns-pilot.receipt-origins';
const receiptFormatter = new Intl.DateTimeFormat('es-PE', {
  timeZone: 'America/Lima', dateStyle: 'short', timeStyle: 'short',
});

function receiptTime(timestamp) {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? 'Fecha sin registrar' : receiptFormatter.format(date);
}

const getRequestId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `mesa-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const readPending = () => {
  try {
    const value = window.localStorage.getItem(PENDING_KEY);
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
};

const readMode = () => {
  try {
    const stored = window.localStorage.getItem(MODE_KEY);
    if (stored === 'union' || stored === 'receive') return stored;
    return readPending() ? 'union' : 'receive';
  } catch {
    return 'receive';
  }
};

const readJson = (key, fallback) => {
  try {
    const value = window.localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
};

const normalizeCode = (value) => String(value || '').trim().toUpperCase();

const PREPESAJE_INVALID = 'QR PREPESAJE inválido. Verifique que tenga solo v:1 y label_id, y vuelva a escanear.';
const PREPESAJE_UNKNOWN = 'Etiqueta PREPESAJE desconocida o no vigente. Verifique el QR y vuelva a escanear.';
const LABEL_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function parsePrepesajeQr(value) {
  const raw = String(value || '').trim();
  if (!raw.startsWith('{') && !raw.startsWith('[')) return { kind: 'literal', value: raw };
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return { kind: 'json', valid: false };
  }
  if (!payload || Array.isArray(payload) || typeof payload !== 'object') return { kind: 'json', valid: false };
  if (payload.v !== 1 || typeof payload.label_id !== 'string' || !LABEL_ID_PATTERN.test(payload.label_id.trim())) {
    return { kind: 'json', valid: false };
  }
  return { kind: 'json', valid: true, labelId: payload.label_id.trim() };
}

function aliasHasLabelId(alias, labelId) {
  const raw = String(alias || '').trim();
  if (!raw) return false;
  if (raw.startsWith('L1|')) return normalizeCode(raw.slice(3)) === normalizeCode(labelId);
  const parsed = parsePrepesajeQr(raw);
  return parsed.kind === 'json' && parsed.valid && normalizeCode(parsed.labelId) === normalizeCode(labelId);
}

function labelIdFromAlias(alias) {
  const raw = String(alias || '').trim();
  if (raw.startsWith('L1|') && LABEL_ID_PATTERN.test(raw.slice(3))) return raw.slice(3);
  const parsed = parsePrepesajeQr(raw);
  return parsed.kind === 'json' && parsed.valid ? parsed.labelId : null;
}

const weightValue = (value) => {
  const normalized = String(value || '').trim().replace(',', '.');
  if (!/^\d+(?:\.\d{1,3})?$/.test(normalized)) return null;
  const number = Number(normalized);
  return Number.isFinite(number) && number > 0 ? normalized : null;
};

async function request(url, body) {
  let response;
  try {
    response = await fetch(url, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch (cause) {
    const error = new Error('No se pudo conectar con la estación.');
    error.kind = 'network';
    error.cause = cause;
    throw error;
  }
  let value = {};
  try {
    value = await response.json();
  } catch {
    value = {};
  }
  if (!response.ok) {
    const error = new Error(value.error || 'No se pudo confirmar la operación. Vuelva a intentarlo.');
    error.status = response.status;
    error.payload = value;
    throw error;
  }
  return value;
}

const UNION_MISMATCH = 'No se puede unir: pieza y color deben coincidir';

function isUnionMismatch(error) {
  return /pieza|color|compatib/i.test(String(error?.message || ''));
}

function mesaOperationError(error, operation) {
  if (operation === 'union' && isUnionMismatch(error)) return UNION_MISMATCH;
  if (operation === 'union' && [404,409].includes(error.status)) return 'Alguna manga ya no está disponible. Revisa los orígenes antes de crear la unión.';
  if (operation === 'receive' && [404,409].includes(error.status)) return 'La manga ya no está disponible para este ingreso. Revisa los ingresos confirmados.';
  if (operation === 'load') return 'No se pudo cargar el estado de mangas. Revise la conexión y vuelva a intentar.';
  if (operation === 'union') return 'No pudimos verificar la unión. Reintenta con las mismas mangas.';
  if (operation === 'receive') return 'No pudimos verificar el ingreso. Reintenta con el mismo peso para recuperar el comprobante.';
  return 'No se pudo completar la operación. Vuelva a intentarlo.';
}

function otContext(unit) {
  const date = unit?.ot_date?.split('-').reverse().join('/') || 'Fecha sin registrar';
  const shift = { DIA: 'Día', NOCHE: 'Noche' }[unit?.ot_shift] || 'Turno sin registrar';
  return `${date} · ${shift}`;
}

function UnitIdentity({ unit, label = 'Identidad seleccionada' }) {
  if (!unit) return null;
  return (
    <section className="mesa-identity scm-active-manga" aria-label={label}>
      <div className="mesa-identity-heading">
        <span>{label}</span>
        <strong>{unit.code}</strong>
      </div>
      <dl className="scm-context-grid">
        <div><dt>Pieza</dt><dd>{unit.piece || 'Sin pieza informada'}</dd></div>
        <div><dt>Color</dt><dd>{unit.color || 'Sin color informado'}</dd></div>
        {!unit.originDetails?.length && <div><dt>Fecha y turno de OT</dt><dd>{otContext(unit)}</dd></div>}
      </dl>
      {unit.originDetails?.length > 0 && <ul className="mesa-identity-origins" aria-label="Fechas y turnos de origen">{unit.originDetails.map((origin) => <li key={origin.code}><strong>{origin.code}</strong><span>{otContext(origin)}</span></li>)}</ul>}
    </section>
  );
}

function ReturnPrintControls({ code, kind = 'retorno' }) {
  const [printerStatus, setPrinterStatus] = useState(null);
  const [printerName, setPrinterName] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const previewUrl = `/api/mesa/retornos/etiquetas/${encodeURIComponent(code)}.svg?formato=50x50`;

  const loadPrinters = async () => {
    setBusy(true);
    try {
      const value = await request('/api/mesa/printer/status');
      setPrinterStatus(value);
      setFeedback(null);
    } catch (error) {
      setFeedback({ type: 'error', text: `${error.message} Revise la conexión y reintente.` });
    } finally {
      setBusy(false);
    }
  };

  const printPhysical = async () => {
    if (!printerName) return;
    setBusy(true);
    setFeedback(null);
    try {
      const value = await request(`/api/mesa/retornos/etiquetas/${encodeURIComponent(code)}/print`, { printer_name: printerName });
      setFeedback({ type: 'success', text: `${value.copies === 1 ? '1 copia enviada' : '2 copias enviadas'} a la cola Windows ${value.printer_name}.` });
    } catch (error) {
      const uncertain = error.payload?.safe_to_retry === false;
      setFeedback({ type: 'error', text: `${error.message} ${uncertain ? 'No repita el pesaje; revise físicamente antes de reintentar solo la impresión.' : 'El retorno se conserva; conecte la impresora y reintente solo la impresión.'}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mesa-return-print-controls">
      <img className="mesa-return-sticker-preview" src={previewUrl} alt={`Vista previa del sticker${kind === 'identidad' ? '' : ' 2up'} de ${code}`} />
      <a href={previewUrl} target="_blank" rel="noreferrer">Abrir vista previa{kind === 'identidad' ? '' : ' 2up'}</a>
      <button type="button" className="btn btn-secondary" onClick={loadPrinters} disabled={busy}>
        {busy ? 'Consultando…' : 'Seleccionar impresora Windows'}
      </button>
      {printerStatus && (
        <>
          <label htmlFor={`return-printer-${code}`}>Cola Windows</label>
          <select id={`return-printer-${code}`} value={printerName} onChange={(event) => setPrinterName(event.target.value)} disabled={busy}>
            <option value="">Selecciona una cola</option>
            {printerStatus.available.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          {printerStatus.available.length === 0 && <small role="status">No hay impresoras Windows conectadas.</small>}
          <button type="button" className="btn btn-primary" onClick={printPhysical} disabled={!printerName || busy}>Imprimir {kind === 'identidad' ? 1 : 2} {kind === 'identidad' ? 'copia' : 'copias'}</button>
        </>
      )}
      {feedback && <p className={`mesa-return-print-feedback ${feedback.type}`} role={feedback.type === 'error' ? 'alert' : 'status'}>{feedback.text}</p>}
    </div>
  );
}

function WeightInput({ value, onChange, disabled, manual = true }) {
  const raw = value.trim().replace(',', '.');
  let error = '';
  if (value && !weightValue(value)) {
    if (/^-?\d+(\.\d+)?$/.test(raw) && Number(raw) <= 0) error = 'El peso debe ser mayor que 0 kg.';
    else if (/^\d+\.\d{4,}$/.test(raw)) error = 'Usa hasta 3 decimales.';
    else error = 'Ingresa un peso en kg con coma o punto, por ejemplo 2,125.';
  }
  return (
    <div className="mesa-weight-input">
      <label htmlFor="mesa-net-weight">Peso NETO {manual ? 'manual' : 'capturado'}</label>
      <div className="mesa-weight-field">
        <input
          id="mesa-net-weight"
          type="text"
          inputMode="decimal"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="0,000"
          disabled={disabled}
          aria-describedby="mesa-net-weight-hint"
          aria-invalid={Boolean(error)}
        />
        <strong>kg</strong>
      </div>
      <p id="mesa-net-weight-hint" aria-live="polite" className={error ? 'mesa-field-error' : undefined}>{error || (manual ? 'Entrada manual explícita · use coma o punto y hasta 3 decimales.' : 'Lectura real de Accura · el NET se usa directamente.')}</p>
    </div>
  );
}

export default function MesaReturnsPilot({ showExamples = false }) {
  const [mode, setMode] = useState(readMode);
  const [units, setUnits] = useState([]);
  const [receipts, setReceipts] = useState([]);
  const [selectedCodes, setSelectedCodes] = useState([]);
  const [selectedLabelIds, setSelectedLabelIds] = useState({});
  const [unionInput, setUnionInput] = useState('');
  const [receiveInput, setReceiveInput] = useState('');
  const [receiveUnit, setReceiveUnit] = useState(null);
  const [netWeight, setNetWeight] = useState('');
  const [pendingUnion, setPendingUnion] = useState(readPending);
  const [receivingPending, setReceivingPending] = useState(Boolean(readPending()));
  const [receiveRequestId, setReceiveRequestId] = useState('');
  const receiveInputRef = useRef(null);
  const [receiveResult, setReceiveResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [scaleStatus, setScaleStatus] = useState({ modo: null, disponible: false, base: null, kg: null, mensaje: '' });
  const [scaleStatusWarning, setScaleStatusWarning] = useState('');
  const [scaleBusy, setScaleBusy] = useState(false);
  const scaleCaptures = useRef(new Map());
  const { notices, notify: setNotice, dismiss } = useMesaNotices();
  const unionStepNotice = useRef(null);
  const notifyStep = (notice) => {
    if (mode !== 'union') return setNotice(notice);
    if (unionStepNotice.current) dismiss(unionStepNotice.current);
    unionStepNotice.current = setNotice(notice);
  };

  const refreshScaleStatus = async () => {
    try {
      const status = await getMesaScaleStatus();
      setScaleStatus(status);
      setScaleStatusWarning(status.modo ? '' : 'La estación no entregó un modo de balanza válido. Seleccione modo manual o conecte Accura y reintente.');
      return status;
    } catch (error) {
      setScaleStatus({ modo: null, disponible: false, base: null, kg: null, mensaje: '' });
      setScaleStatusWarning(scaleErrorMessage(error, 'No se pudo consultar la configuración de la balanza.'));
      throw error;
    }
  };

  const refreshState = async () => {
    const value = await request(STATE_URL);
    if (!Array.isArray(value?.units) || !Array.isArray(value?.receipts)) throw new Error('Catálogo incompleto');
    // En el piloto las seis mangas de ejemplo pertenecen a la misma OT ficticia.
    const nextUnits = (value.units || []).map((unit) =>
      showExamples && /^OFDEMO-OT101-M00[1-6]$/.test(unit.code)
        ? { ot_date: '2026-11-17', ot_shift: 'DIA', ...unit }
        : unit
    );
    setUnits(nextUnits);
    const knownOrigins = readJson(ORIGINS_KEY, {});
    const nextReceipts = value.receipts.map((receipt) => ({
      ...receipt,
      origins: receipt.origins || knownOrigins[normalizeCode(receipt.code)] || nextUnits.find((unit) => normalizeCode(unit.code) === normalizeCode(receipt.code))?.origins || [],
    }));
    setReceipts(nextReceipts);
    return { units: nextUnits, receipts: nextReceipts };
  };

  const reconcilePending = (nextUnits) => {
    const pending = nextUnits.filter((unit) => unit.status === 'pending');
    const recovered = pending.find((unit) => unit.code === pendingUnion?.code) || pending[0];
    if (recovered) {
      const origins = (Array.isArray(recovered.origins) ? recovered.origins : []).map((originCode) => {
        const origin = nextUnits.find((unit) => normalizeCode(unit.code) === normalizeCode(originCode));
        return origin || { code: originCode };
      });
      const firstLot = recovered.lot || origins[0]?.lot || null;
      const sameLot = origins.every((origin) => (origin.lot || null) === firstLot);
      setPendingUnion({ code: recovered.code, piece: recovered.piece || origins[0]?.piece, color: recovered.color || origins[0]?.color, lot: sameLot ? firstLot : null, origins });
      setReceivingPending(true);
    } else {
      setPendingUnion(null);
      setReceivingPending(false);
      window.localStorage.removeItem(PENDING_KEY);
    }
  };

  useEffect(() => {
    let active = true;
    refreshScaleStatus()
      .then((status) => {
        if (!active) return;
      })
      .catch(() => {});
    refreshState()
      .then(({ units: nextUnits }) => {
        if (!active) return;
        setLoadError(false);
        reconcilePending(nextUnits);
      })
      .catch((error) => {
        if (active) {
          setLoadError(true);
          setNotice({ type: 'error', text: mesaOperationError(error, 'load') });
        }
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!pendingUnion || !receivingPending) return undefined;
    const focusTimer = window.setTimeout(() => receiveInputRef.current?.focus(), 0);
    return () => window.clearTimeout(focusTimer);
  }, [pendingUnion?.code, receivingPending, mode]);

  const retryLoad = async () => {
    if (loading) return;
    setLoading(true);
    setLoadError(false);
    try {
      const { units: nextUnits } = await refreshState();
      reconcilePending(nextUnits);
    } catch (error) {
      setLoadError(true);
      setNotice({ type: 'error', text: mesaOperationError(error, 'load') });
    } finally {
      setLoading(false);
    }
  };

  const selectedUnits = useMemo(
    () => selectedCodes.map((code) => units.find((unit) => normalizeCode(unit.code) === code)).filter(Boolean),
    [selectedCodes, units],
  );
  const currentWeight = weightValue(netWeight);
  const controlsDisabled = loading || loadError || busy || scaleBusy;
  const alreadyReceived = receiveUnit && (receiveUnit.status === 'received' || receiveResult);
  const accuraMode = scaleStatus.modo === 'accura';
  const manualMode = scaleStatus.modo === 'manual';
  const scaleHasWeight = Boolean(weightValue(scaleStatus.kg));
  const returnScaleReady = accuraMode && scaleStatus.disponible && scaleStatus.base === 'NT' && scaleHasWeight;
  const returnScaleLabel = !accuraMode
    ? (manualMode ? 'Balanza manual' : 'Balanza sin configurar')
    : !scaleStatus.disponible
      ? 'Balanza Accura no disponible'
      : returnScaleReady
        ? 'Balanza Accura lista'
        : 'Balanza Accura conectada · esperando lectura';

  const resolveUnit = (value) => {
    const parsed = parsePrepesajeQr(value);
    if (parsed.kind === 'json') {
      if (!parsed.valid) return { unit: null, error: PREPESAJE_INVALID };
      const unit = units.find((candidate) => (candidate.aliases || []).some((alias) => aliasHasLabelId(alias, parsed.labelId)));
      return { unit: unit || null, labelId: parsed.labelId, error: unit ? null : PREPESAJE_UNKNOWN };
    }
    const scanned = normalizeCode(parsed.value);
    const unit = units.find((candidate) => [candidate.code, ...(candidate.aliases || [])].some(alias => normalizeCode(alias) === scanned));
    const matchedAlias = unit && [unit.code, ...(unit.aliases || [])].find(alias => normalizeCode(alias) === scanned);
    return {
      unit: unit || null,
      labelId: labelIdFromAlias(matchedAlias),
      error: null,
    };
  };
  const findUnit = (value) => resolveUnit(value).unit;
  const requestSlot = (unit) => unit.cycle_id ? `${normalizeCode(unit.code)}:${unit.cycle_id}` : normalizeCode(unit.code);
  const availableUnits = units.filter((unit) => unit.status === 'available');
  const pendingUnions = useMemo(() => {
    const fromState = units.filter((unit) => unit.status === 'pending').map((unit) => ({
      code: unit.code,
      piece: unit.piece,
      color: unit.color,
      lot: unit.lot || null,
      origins: (Array.isArray(unit.origins) ? unit.origins : []).map((code) => findUnit(code) || { code }),
    }));
    const candidates = pendingUnion ? [pendingUnion, ...fromState] : fromState;
    return candidates.filter((candidate, index, all) => all.findIndex((item) => normalizeCode(item.code) === normalizeCode(candidate.code)) === index);
  }, [pendingUnion, units]);

  function linkedMessage(code) {
    const parent = units.find(unit => normalizeCode(unit.code) !== code && unit.origins?.includes(code))
      || pendingUnions.find(unit => unit.origins.some(origin => normalizeCode(origin.code) === code));
    if (!parent) return '';
    return parent.status === 'received' || receipts.some(receipt => receipt.code === parent.code)
      ? `Esta manga ya se recibió con la unión ${parent.code}. Consulta el comprobante de ${parent.code}.`
      : `Esta manga pertenece a ${parent.code}. Escanea el QR de ${parent.code}.`;
  }

  const addOriginCode = (rawCode) => {
    const resolved = resolveUnit(rawCode);
    if (controlsDisabled) return;
    if (resolved.error) {
      setNotice({ type: 'error', text: resolved.error });
      return;
    }
    const code = normalizeCode(resolved.unit?.code || rawCode);
    if (!code) return;
    const unit = resolved.unit || findUnit(code);
    if (!unit) {
      setNotice({ type: 'error', text: resolved.error || 'Manga desconocida. Verifique el QR y vuelva a escanear.' });
      return;
    }
    const linked = linkedMessage(code);
    if (linked || unit.status !== 'available') {
      const fallback = unit.status === 'received' ? 'Esta manga ya tiene una recepción registrada.' : 'Esta manga no está disponible como origen. Escanea otra manga.';
      setNotice({ type: 'error', text: linked || fallback });
      return;
    }
    if (selectedCodes.includes(code)) {
      setNotice({ type: 'error', text: 'Ese QR ya está en la unión. Cada origen se incorpora una sola vez.' });
      return;
    }
    const first = selectedUnits[0];
    if (first && (first.piece !== unit.piece || first.color !== unit.color)) {
      setNotice({ type: 'error', text: UNION_MISMATCH });
      return;
    }
    setSelectedCodes((codes) => [...codes, code]);
    if (resolved.labelId) setSelectedLabelIds((labels) => ({ ...labels, [code]: resolved.labelId }));
    setUnionInput('');
    notifyStep({ type: 'info', text: 'Origen incorporado. Puede agregar otro QR compatible.' });
  };

  const addOrigin = (event) => {
    event?.preventDefault();
    addOriginCode(unionInput);
  };

  const removeOrigin = (code) => {
    setSelectedCodes((codes) => codes.filter((item) => item !== code));
    setSelectedLabelIds((labels) => { const next = { ...labels }; delete next[code]; return next; });
    setNotice({ type: 'info', text: 'Origen retirado de la selección. Todavía no se registró ningún movimiento.' });
  };

  const createUnion = async () => {
    if (selectedCodes.length < 2 || controlsDisabled) return;
    setBusy(true);
    try {
      const labelIds = Object.fromEntries(selectedCodes.filter((code) => selectedLabelIds[code]).map((code) => [code, selectedLabelIds[code]]));
      const unionPayload = { codes: selectedCodes, ...(Object.keys(labelIds).length ? { label_ids: labelIds } : {}) };
      const value = await request('/api/mesa/unions', unionPayload);
      const code = normalizeCode(value.code);
      if (!code) throw new Error('No se recibió el código de la unión. Reintente con las mismas mangas.');
      const firstLot = selectedUnits[0]?.lot || null;
      const sameLot = selectedUnits.every((unit) => (unit.lot || null) === firstLot);
      const nextPending = { code, piece: selectedUnits[0]?.piece, color: selectedUnits[0]?.color, lot: sameLot ? firstLot : null, origins: selectedUnits };
      window.localStorage.setItem(PENDING_KEY, JSON.stringify(nextPending));
      const knownOrigins = readJson(ORIGINS_KEY, {});
      knownOrigins[code] = selectedUnits;
      window.localStorage.setItem(ORIGINS_KEY, JSON.stringify(knownOrigins));
      setPendingUnion(nextPending);
      setSelectedCodes([]);
      setSelectedLabelIds({});
      setUnionInput('');
      setReceiveInput('');
      setReceiveUnit(null);
      setReceiveResult(null);
      setNetWeight('');
      setReceivingPending(true);
      let refreshed = true;
      try {
        await refreshState();
      } catch {
        refreshed = false;
        setLoadError(true);
      }
      notifyStep({
        type: 'success',
        text: refreshed
          ? `Identidad ${code} creada. Imprima el sticker y escanee su QR nuevo antes de recibir.`
          : `Identidad ${code} creada. Pulsa Reintentar para actualizar las mangas.`,
      });
    } catch (error) {
      if ([404,409].includes(error.status) && !isUnionMismatch(error)) {
        try {
          const { units: latest } = await refreshState();
          setSelectedCodes(codes => codes.filter(code => latest.some(unit => unit.code === code && unit.status === 'available')));
        } catch { setLoadError(true); }
      }
      setNotice({ type: 'error', text: mesaOperationError(error, 'union') });
    } finally {
      setBusy(false);
    }
  };

  const scanReceiveCode = (rawCode) => {
    const resolved = resolveUnit(rawCode);
    if (controlsDisabled) return;
    if (resolved.error) {
      setReceiveUnit(null);
      setReceiveResult(null);
      setNetWeight('');
      setNotice({ type: 'error', text: resolved.error || 'No se encontró esa identidad. Revise el QR y vuelva a escanear.' });
      return;
    }
    const code = normalizeCode(resolved.unit?.code || rawCode);
    if (!code) return;
    if (pendingUnion && receivingPending) {
      const expectedCode = normalizeCode(pendingUnion.code);
      const candidate = pendingUnions.find((item) => normalizeCode(item.code) === expectedCode) || pendingUnion;
      if (code !== expectedCode) {
        const linked = linkedMessage(code);
        setReceiveUnit(null);
        setReceiveResult(null);
        setNetWeight('');
        setReceiveRequestId('');
        notifyStep({ type: 'error', text: [`Esperaba ${candidate.code}. Escaneaste ${code}.`, linked].filter(Boolean).join(' ') });
        return;
      }
      setPendingUnion(candidate);
      setReceiveUnit({ code: candidate.code, piece: candidate.piece, color: candidate.color, lot: candidate.lot, origins: candidate.origins.map((origin) => origin.code), originDetails: candidate.origins });
      const requestIds = readJson(REQUEST_KEY, {});
      const requestId = requestIds[normalizeCode(candidate.code)] || getRequestId();
      setReceiveRequestId(requestId);
      requestIds[normalizeCode(candidate.code)] = requestId;
      window.localStorage.setItem(REQUEST_KEY, JSON.stringify(requestIds));
      notifyStep({ type: 'info', text: accuraMode ? 'QR nuevo confirmado. Pulse Leer balanza para obtener el NETO.' : 'QR nuevo confirmado. Ingrese la lectura NETO manual.' });
      return;
    }
    const unit = findUnit(code);
    const linked = linkedMessage(code);
    if (!unit || linked) {
      setReceiveUnit(null);
      setReceiveResult(null);
      setNetWeight('');
      setNotice({ type: 'error', text: linked || 'No se encontró esa identidad. Revise el QR y vuelva a escanear.' });
      return;
    }
    if (unit.status === 'received') {
      const originDetails = (unit.origins || []).map((originCode) => findUnit(originCode) || { code: originCode });
      const receipt = receipts.find((item) => normalizeCode(item.code) === code);
      setReceiveUnit({ ...unit, label_id: resolved.labelId, originDetails });
      setReceiveResult(receipt ? { ...receipt, origins: originDetails } : null);
      setNetWeight('');
      notifyStep({ type: 'info', text: 'Esta manga ya tiene una recepción registrada.' });
      return;
    }
    if (unit.status !== 'available') {
      setReceiveUnit(null);
      setNetWeight('');
      setReceiveResult(null);
      setNotice({ type: 'error', text: unit.status === 'pending' ? `Retoma la unión ${code} y escanea su QR.` : 'Esta manga no está disponible para recibir. Revisa su estado antes de pesar.' });
      return;
    }
    setReceiveUnit({ ...unit, label_id: resolved.labelId });
    const requestIds = readJson(REQUEST_KEY, {});
    const requestId = requestIds[requestSlot(unit)] || getRequestId();
    setReceiveRequestId(requestId);
    requestIds[requestSlot(unit)] = requestId;
    window.localStorage.setItem(REQUEST_KEY, JSON.stringify(requestIds));
    setReceiveResult(null);
    setNetWeight('');
    setNotice({ type: 'info', text: accuraMode ? 'Identidad resuelta. Pulse Leer balanza para obtener el NETO.' : 'Identidad resuelta. Ingrese el peso NETO manual para confirmar.' });
  };

  const scanReceive = (event) => {
    event?.preventDefault();
    scanReceiveCode(receiveInput);
  };

  const captureReturnWeight = async () => {
    if (!receiveUnit || scaleBusy || alreadyReceived) return;
    setScaleBusy(true);
    const code = normalizeCode(receiveUnit.code);
    const previous = scaleCaptures.current.get(code) || {};
    const operationId = previous.operationId || getRequestId();
    try {
      const latest = await refreshScaleStatus();
      if (latest.modo !== 'accura' || !latest.disponible) {
        setNotice({ type: 'error', text: latest.mensaje || 'Accura no está disponible. Reintente cuando la estación indique ST.' });
        return;
      }
      setScaleStatus(latest);
      if (latest.base !== 'NT') {
        setNotice({ type: 'error', text: 'La balanza Accura no está configurada en base NT para retornos.' });
        return;
      }
      const value = await captureMesaScale({
        codigo: code,
        token: previous.token,
        operationId,
      });
      if (!weightValue(value.kg)) throw new Error('La balanza no devolvió un NET válido.');
      scaleCaptures.current.set(code, { operationId, token: value.token });
      setNetWeight(value.kg);
      setScaleStatus((current) => ({ ...current, kg: value.kg, disponible: true, mensaje: value.mensaje || current.mensaje }));
      notifyStep({ type: 'success', text: `Lectura Accura capturada para ${code}: ${value.kg} kg NET.` });
    } catch (error) {
      scaleCaptures.current.set(code, { operationId, token: previous.token });
      setNotice({ type: 'error', text: scaleErrorMessage(error, 'No se pudo actualizar/capturar la balanza. Reintente con el mismo código.') });
    } finally {
      setScaleBusy(false);
    }
  };

  const receive = async () => {
    if (!receiveUnit || !currentWeight || controlsDisabled || alreadyReceived) return;
    setBusy(true);
    try {
      const requestId = receiveRequestId || getRequestId();
      if (!receiveRequestId) {
        const requestIds = readJson(REQUEST_KEY, {});
        requestIds[requestSlot(receiveUnit)] = requestId;
        window.localStorage.setItem(REQUEST_KEY, JSON.stringify(requestIds));
        setReceiveRequestId(requestId);
      }
      const scaleCapture = scaleCaptures.current.get(normalizeCode(receiveUnit.code));
      const value = await request('/api/mesa/receive', {
        code: receiveUnit.code,
        ...(receiveUnit.label_id ? { label_id: receiveUnit.label_id } : {}),
        net_kg: currentWeight,
        request_id: requestId,
        ...(scaleCapture?.token ? { scale_token: scaleCapture.token } : {}),
      });
      if (value?.code !== receiveUnit.code || !weightValue(value.net_kg) || Number(value.net_kg) !== Number(currentWeight)) {
        throw new Error('Comprobante incompleto');
      }
      const originDetails = receiveUnit.originDetails || (receiveUnit.origins || []).map((code) => findUnit(code) || { code });
      const receipt = { ...value, origins: originDetails };
      const knownOrigins = readJson(ORIGINS_KEY, {});
      knownOrigins[normalizeCode(value.code)] = originDetails;
      window.localStorage.setItem(ORIGINS_KEY, JSON.stringify(knownOrigins));
      const requestIds = readJson(REQUEST_KEY, {});
      delete requestIds[requestSlot(receiveUnit)];
      window.localStorage.setItem(REQUEST_KEY, JSON.stringify(requestIds));
      setReceiveResult(receipt);
      setReceipts((current) => [...current, receipt]);
      setUnits((current) => current.map((unit) => normalizeCode(unit.code) === normalizeCode(value.code) ? { ...unit, status: 'received' } : unit));
      if (pendingUnion && normalizeCode(value.code) === normalizeCode(pendingUnion.code)) {
        window.localStorage.removeItem(PENDING_KEY);
        setPendingUnion(null);
        setReceivingPending(false);
      }
      try { await refreshState(); } catch { /* la confirmación ya fue devuelta por receive */ }
      setReceiveInput('');
      setReceiveUnit(null);
      setNetWeight('');
      setReceiveRequestId('');
      window.setTimeout(() => receiveInputRef.current?.focus(), 0);
      notifyStep({ type: 'success', text: `Retorno confirmado: ${value.code}. El ingreso se registró una sola vez.` });
    } catch (error) {
      if ([404,409].includes(error.status)) {
        try {
          const latest = await refreshState();
          const receipt = latest.receipts.find(item => item.code === receiveUnit.code);
          const unit = latest.units.find(item => item.code === receiveUnit.code);
          setNetWeight('');
          if (receipt && unit) {
            const origins = unit.origins.map(code => latest.units.find(item => item.code === code) || { code });
            setReceiveUnit({ ...unit, label_id: receiveUnit.label_id, originDetails: origins });
            setReceiveResult({ ...receipt, origins });
            notifyStep({ type: 'info', text: 'Esta manga ya tiene una recepción registrada.' });
            return;
          }
          setReceiveUnit(null);
          setReceiveResult(null);
        } catch {
          setLoadError(true);
          setNotice({ type: 'error', text: mesaOperationError(error, 'load') });
          return;
        }
      }
      notifyStep({ type: 'error', text: mesaOperationError(error, 'receive') });
    } finally {
      setBusy(false);
    }
  };

  const loadExample = (code) => {
    if (mode === 'union') {
      setUnionInput(code);
      addOriginCode(code);
    } else {
      setReceiveInput(code);
      scanReceiveCode(code);
    }
  };

  const clearReceiveContext = () => {
    setReceiveInput('');
    setReceiveUnit(null);
    setReceiveResult(null);
    setNetWeight('');
    setReceiveRequestId('');
  };

  const switchMode = (nextMode) => {
    if (nextMode === mode || busy || scaleBusy) return;
    clearReceiveContext();
    setReceivingPending(nextMode === 'union' && Boolean(pendingUnion));
    setMode(nextMode);
    window.localStorage.setItem(MODE_KEY, nextMode);
  };

  const renderReceiveFlow = (headingId, headingText, unionContext = false) => (
    <section className="mesa-flow-section" aria-labelledby={headingId}>
      <div className="mesa-section-heading"><div><h2 id={headingId}>{headingText}</h2></div></div>
      {pendingUnion && (
        <section className="mesa-pending-union" aria-label="Unión pendiente de pesaje">
          <div className="mesa-pending-copy"><span>Unión pendiente</span><strong>{pendingUnion.code}</strong><p>Imprima el sticker y escanee el QR nuevo antes de introducir el peso.</p><ul className="mesa-pending-origins">{pendingUnion.origins.map((origin) => <li key={origin.code}>{origin.code} · {otContext(origin)}</li>)}</ul><img className="mesa-qr-preview" src={`/api/mesa/qr/${encodeURIComponent(pendingUnion.code)}.svg`} alt={`QR de ${pendingUnion.code}`} /></div>
          <div className="mesa-pending-actions">
            <ReturnPrintControls code={pendingUnion.code} kind="identidad" />
            {!receivingPending && (
              <button type="button" className="btn btn-secondary" disabled={controlsDisabled} onClick={() => {
                setReceivingPending(true);
                setReceiveInput('');
                setReceiveUnit(null);
                setNetWeight('');
                setNotice({ type: 'info', text: `Retomada la unión ${pendingUnion.code}. Escanee su QR nuevo.` });
              }}>Retomar esta unión</button>
            )}
             </div>
            </section>
      )}
      {pendingUnion && receivingPending && <p className="mesa-continue-other"><button type="button" className="mesa-link-button" disabled={controlsDisabled} onClick={() => {
        clearReceiveContext();
        setReceivingPending(false);
        if (unionContext) {
          setMode('receive');
          window.localStorage.setItem(MODE_KEY, 'receive');
          setNotice({ type: 'info', text: `Unión ${pendingUnion.code} pendiente. Pesar y recibir quedó listo para un retorno individual.` });
        } else {
          setNotice({ type: 'info', text: 'Puede recibir otra manga. La unión pendiente queda disponible para retomarla después.' });
        }
      }}>{unionContext ? 'Ir a retorno individual' : 'Recibir otra manga mientras tanto'}</button></p>}
      <form className="mesa-scan-form scm-scan-row" onSubmit={scanReceive}>
        <label htmlFor={pendingUnion && receivingPending ? 'mesa-new-qr' : 'mesa-receive-qr'}>{pendingUnion && receivingPending ? 'Escanear QR nuevo' : 'Escanear manga a recibir'}</label>
        <div className="mesa-scan-controls scm-scan-row"><input ref={receiveInputRef} id={pendingUnion && receivingPending ? 'mesa-new-qr' : 'mesa-receive-qr'} value={receiveInput} onChange={(event) => setReceiveInput(event.target.value)} autoComplete="off" placeholder={pendingUnion && receivingPending ? pendingUnion.code : 'OFDEMO-OT101-M001'} /><button type="submit" className="btn btn-primary" disabled={!receiveInput.trim() || controlsDisabled}>Resolver QR</button></div>
        <small>{pendingUnion && receivingPending ? 'No se permite recibir la unión hasta validar exactamente su nuevo QR.' : 'Puede ingresar manualmente el código si no hay lector conectado.'}</small>
      </form>
      {receiveUnit && <UnitIdentity unit={receiveUnit} label={receivingPending ? 'Nueva identidad escaneada' : 'Manga escaneada'} />}
    </section>
  );

  return (
    <section className="mesa-returns-pilot app" aria-label="Segunda estación de pesaje de Armado">
      <header className="header">
        <div>
          <h1>⚖️ Sistema de Pesado - ENVAPERU</h1>
        </div>
        <div className={`connection-badge ${accuraMode && scaleStatus.disponible ? 'connected' : ''}`}>
          {loading ? 'Cargando mangas…' : loadError ? 'Mangas sin actualizar' : returnScaleLabel}
        </div>
        {loadError && <button type="button" className="btn btn-secondary mesa-retry-load" onClick={retryLoad}>Reintentar</button>}
      </header>

      <nav className="tab-nav" role="tablist" aria-label="Tareas de la estación">
        <button type="button" role="tab" aria-label="Pesar y recibir" aria-selected={mode === 'receive'} className={`tab-btn ${mode === 'receive' ? 'active' : ''}`} onClick={() => switchMode('receive')} disabled={busy || scaleBusy}>
          Pesar y recibir
        </button>
        <button type="button" role="tab" aria-label="Unión de mangas" aria-selected={mode === 'union'} className={`tab-btn ${mode === 'union' ? 'active' : ''}`} onClick={() => switchMode('union')} disabled={busy || scaleBusy}>
          Unión de mangas
        </button>
      </nav>

      <div className={`mesa-pilot-grid scm-weighing-layout ${mode === 'receive' ? 'mesa-reception' : ''}`}>
        <main className="mesa-operation panel">
          <h2 className="panel-header">Retornos de Armado</h2>
          <div className="panel-body">

          {mode === 'union' ? (
            <>
              <section className="mesa-flow-section" aria-labelledby="mesa-union-title">
                <div className="mesa-section-heading">
                  <div><h2 id="mesa-union-title">Seleccione las mangas que se vaciarán juntas</h2></div>
                  <strong className="mesa-count">{selectedCodes.length} / 2 mínimo</strong>
                </div>
                <form className="mesa-scan-form scm-scan-row" onSubmit={addOrigin}>
                  <label htmlFor="mesa-union-scan">Escanear manga de origen</label>
                  <div className="mesa-scan-controls scm-scan-row"><input id="mesa-union-scan" value={unionInput} onChange={(event) => setUnionInput(event.target.value)} autoComplete="off" placeholder="OFDEMO-OT101-M001" /><button type="submit" className="btn btn-primary" disabled={!unionInput.trim() || controlsDisabled}>Agregar origen</button></div>
                  <small>También puede escribir el código y pulsar Enter.</small>
                </form>
                {selectedUnits.length > 0 ? (
                  <div className="mesa-origin-list" aria-label="Orígenes seleccionados">
                    {selectedUnits.map((unit) => <div className="mesa-origin-row" key={unit.code}><div><strong>{unit.code}</strong><span>{unit.piece} · {unit.color} · {otContext(unit)}</span></div><button type="button" className="btn btn-secondary" onClick={() => removeOrigin(normalizeCode(unit.code))} disabled={controlsDisabled}>Quitar</button></div>)}
                    <p className="mesa-origin-rule">Las mangas deben compartir pieza y color.</p>
                  </div>
                ) : <p className="mesa-empty-line">Aún no hay orígenes. Comience con el QR de una manga disponible.</p>}
                <button type="button" className="btn btn-primary mesa-wide-action" onClick={createUnion} disabled={selectedCodes.length < 2 || controlsDisabled}>Crear identidad de unión</button>
              </section>
              {pendingUnion && renderReceiveFlow('mesa-union-receive-title', 'Pesar la unión creada', true)}
            </>
          ) : renderReceiveFlow('mesa-receive-title', 'Escanee la identidad que retorna')}
          </div>
        </main>

        <section className="panel" aria-labelledby="mesa-scale-title">
            <h2 id="mesa-scale-title" className="panel-header">Lectura de balanza</h2>
            <div className="panel-body">
              <div className={`scm-live-weight ${accuraMode ? 'connected' : 'manual'}`} aria-label={`Lectura neta ${accuraMode ? 'Accura' : 'manual'}`}>
                <span className="scm-live-weight-label">Peso neto de retorno</span>
                <div className="scm-live-weight-reading">
                  <strong>{currentWeight ? Number(currentWeight).toFixed(3) : '—'}</strong><span>kg</span>
                </div>
                <small>{accuraMode
                  ? (scaleStatus.disponible
                    ? (scaleHasWeight ? 'Accura · base NT · captura bajo demanda' : (scaleStatus.mensaje || 'Accura conectada · espere estabilización y vuelva a leer'))
                    : (scaleStatus.mensaje || 'Accura no disponible'))
                  : 'Entrada manual explícita'}</small>
              </div>
              {scaleStatusWarning && <div className="mesa-scale-warning-wrap"><p className="mesa-scale-warning" role="status">{scaleStatusWarning}</p><button type="button" className="btn btn-secondary" onClick={() => refreshScaleStatus().catch(() => {})} disabled={scaleBusy || controlsDisabled}>Reintentar estado de balanza</button></div>}
              {accuraMode ? (
                <div className="mesa-scale-capture-actions">
                  <button type="button" className="btn btn-secondary" onClick={() => refreshScaleStatus().catch(() => {})} disabled={scaleBusy || controlsDisabled}>
                    Actualizar estado de balanza
                  </button>
                  <button type="button" className="btn btn-secondary" onClick={captureReturnWeight} disabled={!receiveUnit || !scaleStatus.disponible || scaleBusy || controlsDisabled || Boolean(alreadyReceived)}>
                    {scaleBusy ? 'Leyendo…' : currentWeight ? 'Volver a leer balanza' : 'Leer balanza'}
                  </button>
                  <WeightInput value={netWeight} onChange={() => {}} manual={false} disabled />
                </div>
              ) : (
                <div className="mesa-manual-weight-box">
                  <WeightInput value={netWeight} onChange={setNetWeight} disabled={!manualMode || !receiveUnit || controlsDisabled || Boolean(alreadyReceived)} />
                </div>
              )}
              <button type="button" className="btn btn-primary mesa-wide-action" onClick={receive} disabled={!receiveUnit || !currentWeight || controlsDisabled || Boolean(alreadyReceived) || (!manualMode && !(accuraMode && scaleStatus.base === 'NT'))}>{busy ? 'Confirmando…' : alreadyReceived ? 'Ingreso ya registrado' : 'Pesar y recibir'}</button>
               {receiveResult && <section className="mesa-success-result" aria-label="Retorno confirmado"><div className="mesa-success-copy"><strong>{receiveResult.net_kg} kg netos registrados</strong><span>Movimiento único confirmado para {receiveResult.code} · {receiptTime(receiveResult.created_at)}</span>{receiveResult.origins?.length > 0 && <span>Procedencias: {receiveResult.origins.map((origin) => `${origin.code} · ${otContext(origin)}`).join(' · ')}</span>}</div><img className="mesa-qr-preview" src={`/api/mesa/qr/${encodeURIComponent(receiveResult.code)}.svg`} alt={`QR de ${receiveResult.code}`} /><ReturnPrintControls code={receiveResult.code} /></section>}
            </div>
           </section>
         <aside className="mesa-reference-column mesa-tools" aria-label="Herramientas de la estación">
          {showExamples && (
            <details className="panel">
              <summary className="mesa-tools-summary">Pruebas sin lector · {availableUnits.length} mangas disponibles</summary>
              <div className="panel-body mesa-example-list">
                {availableUnits.map((unit) => (
                  <div className="mesa-example-row" key={unit.code}>
                    <div><strong>{unit.code}</strong><span>{unit.piece} · {unit.color} · {otContext(unit)}</span></div>
                    <button type="button" className="btn btn-secondary" onClick={() => loadExample(unit.code)} disabled={controlsDisabled}>Cargar código</button>
                  </div>
                ))}
              </div>
            </details>
           )}
          {pendingUnions.length > 0 && (
            <details className="panel">
              <summary className="mesa-tools-summary">Uniones pendientes ({pendingUnions.length})</summary>
              <div className="panel-body">
                {pendingUnions.map((candidate) => (
                  <div className="mesa-example-row" key={candidate.code}>
                    <div><strong>{candidate.code}</strong>
                      {candidate.origins.map((origin) => <span key={origin.code}>{origin.code} · {otContext(origin)}</span>)}
                    </div>
                    <button type="button" className="btn btn-secondary" disabled={controlsDisabled} onClick={() => {
                      setPendingUnion(candidate);
                      window.localStorage.setItem(PENDING_KEY, JSON.stringify(candidate));
                      setReceivingPending(true);
                      clearReceiveContext();
                      setMode('union');
                      window.localStorage.setItem(MODE_KEY, 'union');
                      setNotice({ type: 'info', text: `Escanee el QR de ${candidate.code} para retomar la unión.` });
                    }}>Retomar</button>
                  </div>
                ))}
              </div>
            </details>
        )}
          {receipts.length > 0 && (
            <details className="panel mesa-receipts">
              <summary className="mesa-tools-summary">Ingresos confirmados ({receipts.length})</summary>
              <ul className="panel-body">
                {receipts.slice().reverse().map((receipt) => (
                  <li key={receipt.code}>
                    <div><strong>{receipt.code}</strong><span>{receipt.net_kg} kg · Recibido el {receiptTime(receipt.created_at)}</span></div>
                     <ReturnPrintControls code={receipt.code} />
                  </li>
                ))}
              </ul>
            </details>
          )}
        </aside>
      </div>

      <MesaNotices notices={notices} dismiss={dismiss} />
    </section>
  );
}
