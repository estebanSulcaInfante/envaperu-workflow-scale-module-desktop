import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './MesaInventory.css';
import { MesaNotices, useMesaNotices } from './MesaNotices';
import {
  captureMesaScale,
  getMesaScaleStatus,
  scaleErrorMessage,
} from '../services/mesaScale';

const INVENTORY_API = '/api/mesa/inventario';
const EMPTY_STATE = {
  zonas: [],
  articulos: [],
  mangas: [],
  sesiones: [],
  pendientes: [],
  movimientos: [],
};
const MODE_COPY = {
  c66: {
    title: 'Inventario C66',
    subtitle: 'Conteo de mangas por zona',
  },
  mesa: {
    title: 'Inventario de mesa',
    subtitle: 'Pesaje de pendientes y altas individuales',
  },
  revision: {
    title: 'Revisión de faltantes',
    subtitle: 'Cobertura, movimientos y búsqueda',
  },
};

function newKey() {
  return (
    globalThis.crypto?.randomUUID?.() ||
    `mesa-inv-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

function cleanCode(value) {
  const code = String(value || '').trim();
  return code.startsWith('{') ? code : code.toUpperCase();
}

function parseWeight(value) {
  const normalized = String(value || '')
    .trim()
    .replace(',', '.');
  if (!/^\d+(?:\.\d{1,3})?$/.test(normalized)) return null;
  const number = Number(normalized);
  return Number.isFinite(number) && number >= 0 ? normalized : null;
}

function pathForLabel(code, kind, extension, format) {
  const query = format ? `?formato=${encodeURIComponent(format)}` : '';
  return `${INVENTORY_API}/etiquetas/${encodeURIComponent(code)}/${kind}.${extension}${query}`;
}

async function callInventory(path, options = {}) {
  let response;
  try {
    response = await fetch(`${INVENTORY_API}${path}`, {
      method: options.method || 'GET',
      headers:
        options.body === undefined
          ? undefined
          : { 'Content-Type': 'application/json' },
      ...(options.body === undefined
        ? {}
        : { body: JSON.stringify(options.body) }),
    });
  } catch (cause) {
    const error = new Error(
      'No se pudo conectar con Inventario. Revise la conexión y reintente.',
    );
    error.kind = 'network';
    error.cause = cause;
    throw error;
  }
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    const error = new Error(
      data.error || 'Inventario no pudo completar la operación.',
    );
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function operationMessage(error, fallback) {
  if (error?.kind === 'network' || Number(error?.status) >= 500)
    return `${fallback} Revise la conexión y reintente.`;
  return error?.data?.error || fallback;
}

function NoticeButton({
  children,
  onClick,
  disabled = false,
  secondary = false,
  type = 'button',
}) {
  return (
    <button
      type={type}
      className={`mesa-inventory-btn ${secondary ? 'secondary' : 'primary'}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function LabelPreview({ code, kind }) {
  if (!code) return null;
  const format = '50x50';
  const svgUrl = pathForLabel(code, kind, 'svg', format);
  const tsplUrl = pathForLabel(code, kind, 'tspl', format);
  const printUrl = `${INVENTORY_API}/etiquetas/${encodeURIComponent(code)}/${kind}/print`;
  const [printerStatus, setPrinterStatus] = useState(null);
  const [printerName, setPrinterName] = useState('');
  const [printState, setPrintState] = useState(null);
  const [printerBusy, setPrinterBusy] = useState(false);

  const loadPrinters = async () => {
    setPrinterBusy(true);
    try {
      const response = await fetch('/api/mesa/printer/status');
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || 'No se pudo consultar la cola Windows.');
      setPrinterStatus(value);
      setPrintState(null);
    } catch (error) {
      setPrintState({ type: 'error', text: `${error.message} Revise la conexión y reintente.` });
    } finally {
      setPrinterBusy(false);
    }
  };

  const printPhysical = async () => {
    if (!printerName) return;
    setPrinterBusy(true);
    setPrintState(null);
    try {
      const response = await fetch(printUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ printer_name: printerName }),
      });
      const value = await response.json();
      if (!response.ok) {
        const error = new Error(value.error || 'La impresora no aceptó el trabajo.');
        error.safeToRetry = value.safe_to_retry !== false;
        throw error;
      }
      setPrintState({ type: 'success', text: `${value.copies === 1 ? '1 copia enviada' : '2 copias enviadas'} a la cola Windows ${value.printer_name}.` });
    } catch (error) {
      setPrintState({
        type: 'error',
        text: `${error.message} ${error.safeToRetry === false ? 'No repita el pesaje; revise físicamente antes de reintentar solo la impresión.' : 'El pesaje se conserva; conecte la impresora y reintente solo la impresión.'}`,
      });
    } finally {
      setPrinterBusy(false);
    }
  };

  return (
    <section
      className="mesa-inventory-label"
      aria-label={`Etiqueta de ${code}`}
    >
      <div>
        <span className="mesa-inventory-kicker">Vista previa SVG</span>
        <strong>{code}</strong>
        <span className="mesa-inventory-label-size">50 × 50 mm</span>
        <div className="mesa-inventory-label-actions">
          <a href={svgUrl} target="_blank" rel="noreferrer">
            Abrir SVG
          </a>
          <a href={tsplUrl} download={`${code}-${kind}.tspl`}>
            Descargar TSPL
          </a>
        </div>
        <div className="mesa-inventory-print-controls">
          <button type="button" className="mesa-inventory-btn secondary" onClick={loadPrinters} disabled={printerBusy}>
            {printerBusy ? 'Consultando…' : 'Seleccionar impresora Windows'}
          </button>
          {printerStatus && (
            <>
              <label htmlFor={`printer-${code}-${kind}`}>Cola Windows</label>
              <select id={`printer-${code}-${kind}`} value={printerName} onChange={(event) => setPrinterName(event.target.value)} disabled={printerBusy}>
                <option value="">Selecciona una cola</option>
                {printerStatus.available.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
              {printerStatus.available.length === 0 && <small role="status">No hay impresoras Windows conectadas.</small>}
              <button type="button" className="mesa-inventory-btn primary" onClick={printPhysical} disabled={!printerName || printerBusy}>
                Imprimir {kind === 'identidad' ? 1 : 2} {kind === 'identidad' ? 'copia' : 'copias'}
              </button>
            </>
          )}
          {printState && <p className={`mesa-inventory-print-feedback ${printState.type}`} role={printState.type === 'error' ? 'alert' : 'status'}>{printState.text}</p>}
        </div>
      </div>
      <img src={svgUrl} alt={`QR de ${code}`} />
    </section>
  );
}

function StateSummary({ state }) {
  const observed = new Set(state.sesiones.flatMap((session) => session.lecturas.map((reading) => reading.codigo)));
  return (
    <div className="mesa-inventory-summary" aria-label="Resumen de inventario">
      <span>
        <strong>{observed.size}</strong> mangas observadas
      </span>
      <span>
        <strong>{state.pendientes.length}</strong> pendientes en mesa
      </span>
      <span>
        <strong>{state.movimientos.length}</strong> movimientos
      </span>
    </div>
  );
}

export default function MesaInventory({ initialView = 'c66' }) {
  const lanMode = !['localhost', '127.0.0.1', '::1', ''].includes(
    globalThis.location?.hostname || '',
  );
  const view = lanMode ? 'c66' : initialView;
  const [state, setState] = useState(EMPTY_STATE);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [zone, setZone] = useState('');
  const [article, setArticle] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [scanner, setScanner] = useState('');
  const [sessionBusy, setSessionBusy] = useState(false);
  const [roomCovered, setRoomCovered] = useState(false);
  const [scanBusy, setScanBusy] = useState(false);
  const [discrepancy, setDiscrepancy] = useState(null);
  const [reservedCode, setReservedCode] = useState('');
  const [createBusy, setCreateBusy] = useState(false);
  const [pending, setPending] = useState(null);
  const [gross, setGross] = useState('');
  const [tare, setTare] = useState('0');
  const [weighingBusy, setWeighingBusy] = useState(false);
  const [weighingResult, setWeighingResult] = useState(null);
  const [scaleStatus, setScaleStatus] = useState({ modo: null, disponible: false, base: null, kg: null, mensaje: '' });
  const [scaleStatusWarning, setScaleStatusWarning] = useState('');
  const [scaleBusy, setScaleBusy] = useState(false);
  const [tareConfirmedForNt, setTareConfirmedForNt] = useState(false);
  const scaleCaptures = useRef(new Map());
  const [confirmationReason, setConfirmationReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [lastReceipt, setLastReceipt] = useState(null);
  const [reviewCode, setReviewCode] = useState('');
  const [reviewSearch, setReviewSearch] = useState('');
  const [reviewChecks, setReviewChecks] = useState({
    coverage: false,
    movements: false,
    search: false,
  });
  const [reviewResult, setReviewResult] = useState(null);
  const [missingReason, setMissingReason] = useState('');
  const [sessionFeedback, setSessionFeedback] = useState('');
  const isDesktop = !lanMode;
  const scanRef = useRef(null);
  const operationKeys = useRef(new Map());
  const { notices, notify, dismiss } = useMesaNotices();

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

  const keyFor = (name) => {
    if (!operationKeys.current.has(name)) {
      const storageKey = 'mesa.inventario.peticion.' + name;
      let key = newKey();
      try {
        key = sessionStorage.getItem(storageKey) || key;
        sessionStorage.setItem(storageKey, key);
      } catch {
        // El lector también funciona cuando el navegador desactiva almacenamiento local.
      }
      operationKeys.current.set(name, key);
    }
    return operationKeys.current.get(name);
  };
  const clearKey = (name) => {
    operationKeys.current.delete(name);
    try { sessionStorage.removeItem('mesa.inventario.peticion.' + name); } catch { /* Almacenamiento deshabilitado. */ }
  };
  const focusScanner = useCallback(
    () => window.setTimeout(() => scanRef.current?.focus(), 0),
    [],
  );

  const loadState = useCallback(async () => {
    setLoading(true);
    try {
      const data = await callInventory('/estado');
      const next = { ...EMPTY_STATE, ...data };
      setState(next);
      setLoadFailed(false);
      return next;
    } catch (error) {
      setLoadFailed(true);
      notify({
        type: 'error',
        text: operationMessage(
          error,
          'No se pudo cargar el estado de Inventario.',
        ),
      });
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    loadState();
  }, [loadState]);
  useEffect(() => {
    if (view !== 'mesa') return undefined;
    let active = true;
    refreshScaleStatus()
      .then((status) => {
        if (!active) return;
      })
      .catch(() => {});
    return () => { active = false; };
  }, [view]);
  const selectedZoneName =
    state.zonas.find((item) => item.id === zone)?.nombre || zone || 'Sin zona';
  const net = useMemo(() => {
    const brutoValue = Number(String(gross).replace(',', '.'));
    const tareValue = Number(String(tare).replace(',', '.'));
    return Number.isFinite(brutoValue) && Number.isFinite(tareValue)
      ? brutoValue - tareValue
      : null;
  }, [gross, tare]);
  const accuraMode = scaleStatus.modo === 'accura';
  const manualMode = scaleStatus.modo === 'manual';
  const scaleHasWeight = Boolean(parseWeight(scaleStatus.kg) && Number(String(scaleStatus.kg).replace(',', '.')) > 0);
  const inventoryScaleReady = accuraMode && scaleStatus.disponible && ['GS', 'NT'].includes(scaleStatus.base) && scaleHasWeight;
  const inventoryScaleLabel = !accuraMode
    ? (manualMode ? 'Balanza manual' : 'Balanza sin configurar')
    : !scaleStatus.disponible
      ? 'Balanza Accura no disponible'
      : inventoryScaleReady
        ? 'Balanza Accura lista'
        : 'Balanza Accura conectada · esperando lectura';
  const activeSession = state.sesiones.find((item) => item.id === sessionId);
  const articleNameForReading = (reading) => {
    const id = reading.articulo || state.mangas.find(
      (item) => cleanCode(item.codigo) === cleanCode(reading.codigo),
    )?.articulo;
    const article = state.articulos.find((item) => item.id === id);
    return article ? `${article.nombre} · ${article.color}` : id || 'Artículo sin detalle';
  };
  const filteredMovements = state.movimientos.filter((item) => {
    const query = reviewSearch.trim().toUpperCase();
    return !query || JSON.stringify(item).toUpperCase().includes(query);
  });

  const createSession = async () => {
    if (!zone || sessionBusy) return;
    setSessionBusy(true);
    try {
      const value = await callInventory('/sesiones', {
        method: 'POST',
        body: { zona: zone, clave: keyFor(`session:${zone}`) },
      });
      setSessionId(value.id);
      clearKey(`session:${zone}`);
      setSessionFeedback(`Sesión C66 abierta en ${selectedZoneName}.`);
      await loadState();
      focusScanner();
    } catch (error) {
      notify({
        type: 'error',
        text: operationMessage(error, 'No se pudo abrir la sesión C66.'),
      });
    } finally {
      setSessionBusy(false);
    }
  };

  const resumeSession = (nextSession) => {
    setRoomCovered(false);
    setSessionId(nextSession.id);
    setZone(nextSession.zona || zone);
    setDiscrepancy(null);
    notify({ type: 'info', text: `Sesión ${nextSession.id} retomada.` });
    focusScanner();
  };

  const scanSessionReading = async (event) => {
    event?.preventDefault();
    const code = cleanCode(scanner);
    if (!code || !zone || scanBusy) return;
    setScanBusy(true);
    setDiscrepancy(null);
    try {
      let targetSession = sessionId;
      if (!targetSession) {
        const sessionValue = await callInventory('/sesiones', {
          method: 'POST',
          body: { zona: zone, clave: keyFor(`session:${zone}`) },
        });
        targetSession = sessionValue.id;
        setSessionId(targetSession);
        clearKey(`session:${zone}`);
      }
      const result = await callInventory(
        `/sesiones/${encodeURIComponent(targetSession)}/lecturas`,
        { method: 'POST', body: { codigo: code } },
      );
      setScanner('');
      setSessionFeedback(`${code} · ${result.mensaje || 'Lectura registrada'}`);
      await loadState();
    } catch (error) {
      if (error.data?.preetiqueta) {
        notify({
          type: 'error',
          text: 'Esta etiqueta aún no identifica una manga. Llévala a la estación de pesaje.',
        });
      } else if (error.status === 409 && error.data?.zona_anterior) {
        setDiscrepancy({ code, previousZone: error.data?.zona_anterior || '' });
        notify({
          type: 'info',
          text: error.data?.error || 'La zona del QR no coincide.',
        });
      } else
      notify({
        type: 'error',
        text:
          error.status === 404
            ? error.data?.error || 'QR no reconocido. Revisa la etiqueta antes de crear otra identidad.'
            : operationMessage(error, 'No se pudo registrar la lectura.'),
      });
    } finally {
      setScanBusy(false);
      focusScanner();
    }
  };

  const acceptZoneDiscrepancy = async () => {
    if (!discrepancy || scanBusy) return;
    setScanBusy(true);
    try {
      await callInventory(
        `/sesiones/${encodeURIComponent(sessionId)}/lecturas`,
        {
          method: 'POST',
          body: {
            codigo: discrepancy.code,
            confirmar_zona: true,
            zona_anterior: discrepancy.previousZone,
          },
        },
      );
      setScanner('');
      setDiscrepancy(null);
      setSessionFeedback(
        `${discrepancy.code} registrada en ${selectedZoneName}.`,
      );
      await loadState();
    } catch (error) {
      notify({
        type: 'error',
        text: operationMessage(
          error,
          'No se pudo aceptar la discrepancia de zona.',
        ),
      });
    } finally {
      setScanBusy(false);
      focusScanner();
    }
  };

  const removeReading = async (code) => {
    if (!sessionId || scanBusy) return;
    setScanBusy(true);
    try {
      await callInventory(
        `/sesiones/${encodeURIComponent(sessionId)}/lecturas/${encodeURIComponent(code)}`,
        { method: 'DELETE' },
      );
      notify({
        type: 'info',
        text: `Captura ${code} retirada; no se borró la manga.`,
      });
      await loadState();
    } catch (error) {
      notify({
        type: 'error',
        text: operationMessage(error, 'No se pudo retirar la captura.'),
      });
    } finally {
      setScanBusy(false);
      focusScanner();
    }
  };

  const closeSession = async () => {
    if (!sessionId || sessionBusy) return;
    setSessionBusy(true);
    try {
      const closed = await callInventory(`/sesiones/${encodeURIComponent(sessionId)}/cerrar`, {
        method: 'POST',
        body: roomCovered ? { cobertura: true } : {},
      });
      const date = closed.closed_at ? new Date(closed.closed_at).toLocaleDateString('es-PE') : '';
      setSessionFeedback(`Recorrido cerrado · ${selectedZoneName} · ${closed.cantidad ?? activeSession?.lecturas.length ?? 0} mangas ${date}`);
      setSessionId('');
      setRoomCovered(false);
      setZone('');
      setDiscrepancy(null);
      await loadState();
    } catch (error) {
      notify({
        type: 'error',
        text: operationMessage(error, 'No se pudo cerrar la sesión C66.'),
      });
    } finally {
      setSessionBusy(false);
      focusScanner();
    }
  };

  const registerOld = async (event) => {
    event?.preventDefault();
    if (!article || !zone || createBusy) return;
    const code = cleanCode(reservedCode);
    const key = `old:${code || 'new'}:${zone}:${article}`;
    setCreateBusy(true);
    try {
      const value = await callInventory('/antiguas', {
        method: 'POST',
        body: {
          codigo: code,
          articulo: article,
          zona: zone,
          clave: keyFor(key),
        },
      });
      notify({
        type: 'success',
        text: `${value.codigo} identificada. Completa el pesaje.`,
      });
      const nextState = await loadState();
      if (!nextState) return;
      clearKey(key);
      setReservedCode('');
      setArticle('');
      if (value.codigo) {
        choosePending(value.codigo, nextState.pendientes, nextState);
        window.setTimeout(() => {
          document.querySelector(accuraMode ? '#scale-capture' : '#gross-weight')?.focus();
        }, 0);
      }
    } catch (error) {
      notify({
        type: 'error',
        text: operationMessage(
          error,
          'No se pudo dar de alta la manga antigua.',
        ),
      });
    } finally {
      setCreateBusy(false);
    }
  };

  const choosePending = (
    code,
    pendingItems = state.pendientes,
    stateValue = state,
  ) => {
    setLastReceipt(null);
    const next = pendingItems.find(
      (item) => cleanCode(item.codigo) === cleanCode(code),
    );
    if (!next) {
      const manga = stateValue.mangas.find(
        (item) => cleanCode(item.codigo) === cleanCode(code),
      );
      const receipt = [...stateValue.movimientos]
        .reverse()
        .find(
          (item) =>
            cleanCode(item.codigo) === cleanCode(code) &&
            ['REINGRESO', 'ALTA_INVENTARIO'].includes(item.tipo),
        );
      if (manga?.estado === 'DISPONIBLE' && receipt) {
        setPending({
          ...manga,
          codigo: manga.codigo,
          bruto: '',
          tara: '0',
          neto: manga.neto,
          estado: 'CONFIRMADA',
        });
        setGross('');
        setTare('0');
        setTareConfirmedForNt(false);
        setWeighingResult({ codigo: manga.codigo, neto: manga.neto });
        setConfirmed(true);
        setConfirmationReason('');
        notify({
          type: 'info',
          text: `Ingreso confirmado recuperado para ${manga.codigo}.`,
        });
        return;
      }
      notify({
        type: 'error',
        text: `No hay un pendiente disponible para ${cleanCode(code)}.`,
      });
      return;
    }
    setPending(next);
    setGross(next.bruto || '');
    setTare(next.tara ?? '0');
    setTareConfirmedForNt(false);
    setWeighingResult(
      next.estado === 'PESADA_PENDIENTE_CONFIRMACION' && next.neto
        ? { codigo: next.codigo, neto: next.neto }
        : null,
    );
    setConfirmed(false);
    setConfirmationReason('');
    notify({
      type: 'info',
      text:
        next.estado === 'PESADA_PENDIENTE_CONFIRMACION' && next.neto
          ? `Pesaje ${next.codigo} recuperado. Revise y confirme el neto.`
          : `Pendiente ${next.codigo} seleccionado. Ingrese bruto y tara.`,
    });
  };

  const scanMesa = async (event) => {
    event?.preventDefault();
    const code = cleanCode(scanner);
    if (!code) return;
    let pendingItems = state.pendientes;
    let currentState = state;
    if (!pendingItems.some((item) => cleanCode(item.codigo) === code)) {
      try {
        const fresh = await callInventory('/estado');
        const nextState = { ...EMPTY_STATE, ...fresh };
        pendingItems = nextState.pendientes;
        currentState = nextState;
        setState(nextState);
      } catch (error) {
        notify({
          type: 'error',
          text: operationMessage(
            error,
            'No se pudo actualizar pendientes para el escaneo.',
          ),
        });
        focusScanner();
        return;
      }
    }
    const reserved = currentState.preetiquetas?.find(
      (item) => cleanCode(item.codigo) === code,
    );
    if (reserved) {
      setReservedCode(code);
      setScanner('');
      notify({
        type: 'info',
        text: `${code} está reservada. Selecciona zona, pieza y color para reutilizarla.`,
      });
      window.setTimeout(() => document.querySelector('#individual-zone')?.focus(), 0);
      return;
    }
    choosePending(code, pendingItems, currentState);
    setScanner('');
    focusScanner();
  };

  const captureInventoryWeight = async () => {
    if (!pending || scaleBusy || weighingResult) return;
    setScaleBusy(true);
    try {
      const latest = await refreshScaleStatus();
      if (latest.modo !== 'accura' || !latest.disponible) {
        notify({ type: 'error', text: latest.mensaje || 'Accura no está disponible. Reintente cuando la estación indique ST.' });
        return;
      }
      setScaleStatus(latest);
      const scaleBase = latest.base;
      if (scaleBase === 'NT' && !tareConfirmedForNt) {
        notify({ type: 'error', text: 'Confirme que la balanza está sin tara para usar esta lectura como peso bruto.' });
        return;
      }
      if (!['GS', 'NT'].includes(scaleBase)) {
        notify({ type: 'error', text: 'La base de la balanza Accura no permite pesar inventario.' });
        return;
      }
      const code = cleanCode(pending.codigo);
      const previous = scaleCaptures.current.get(code) || {};
      const operationId = previous.operationId || newKey();
      scaleCaptures.current.set(code, { operationId, token: previous.token, base: scaleBase });
      const value = await captureMesaScale({ codigo: code, token: previous.token, operationId });
      const weight = parseWeight(value.kg);
      if (!weight || Number(weight) <= 0) throw new Error('La balanza no devolvió un peso válido.');
      scaleCaptures.current.set(code, { operationId, token: value.token, base: scaleBase });
      setGross(weight);
      setScaleStatus((current) => ({ ...current, kg: weight, disponible: true, mensaje: value.mensaje || current.mensaje }));
      notify({ type: 'success', text: `Lectura Accura capturada para ${code}: ${weight} kg.` });
    } catch (error) {
      notify({ type: 'error', text: scaleErrorMessage(error, 'No se pudo capturar la lectura. Reintente con el mismo código.') });
    } finally {
      setScaleBusy(false);
    }
  };

  const registerWeighing = async () => {
    if (!pending || net === null || net <= 0 || weighingBusy) return;
    const brutoValue = parseWeight(gross);
    const tareValue = parseWeight(tare);
    if (!brutoValue || !tareValue) {
      notify({
        type: 'error',
        text: 'Bruto y tara deben tener formato numérico con hasta 3 decimales.',
      });
      return;
    }
    setWeighingBusy(true);
    try {
      const scaleCapture = scaleCaptures.current.get(cleanCode(pending.codigo));
      const value = await callInventory('/pesajes', {
        method: 'POST',
        body: {
          codigo: pending.codigo,
          bruto: brutoValue,
          tara: tareValue,
          clave: keyFor(`weigh:${pending.codigo}`),
          ...(scaleCapture?.token ? { scale_token: scaleCapture.token } : {}),
          ...(scaleCapture?.base === 'NT' && scaleCapture?.token ? { confirmar_sin_tara_indicador: true } : {}),
        },
      });
      clearKey(`weigh:${pending.codigo}`);
      setWeighingResult(value);
      notify({
        type: 'success',
        text: `Pesaje registrado: ${value.codigo || pending.codigo}, neto ${value.neto} kg.`,
      });
      await loadState();
    } catch (error) {
      notify({
        type: 'error',
        text: operationMessage(error, 'No se pudo registrar el pesaje.'),
      });
    } finally {
      setWeighingBusy(false);
    }
  };

  const confirmWeighing = async () => {
    const code = weighingResult?.codigo || pending?.codigo;
    if (!code || !confirmationReason.trim() || confirmed || !isDesktop) return;
    try {
      await callInventory('/confirmaciones', {
        method: 'POST',
        body: {
          codigo: code,
          motivo: confirmationReason.trim(),
          clave: keyFor(`confirm:${code}`),
        },
      });
      clearKey(`confirm:${code}`);
      setConfirmed(true);
      notify({ type: 'success', text: `Ingreso ${code} confirmado.` });
      await loadState();
    } catch (error) {
      notify({
        type: 'error',
        text: operationMessage(error, 'No se pudo confirmar el ingreso.'),
      });
    }
  };

  const createIndividual = (event) => registerOld(event);

  const submitReview = async (event) => {
    event?.preventDefault();
    const code = cleanCode(reviewCode || scanner);
    if (!code || !isDesktop) return;
    try {
      const value = await callInventory('/revision', {
        method: 'POST',
        body: {
          codigo: code,
          cobertura: reviewChecks.coverage,
          movimientos_revisados: reviewChecks.movements,
          busqueda: reviewChecks.search,
        },
      });
      setReviewResult({ ...value, codigo: code });
      notify({ type: 'success', text: `Revisión de ${code} registrada.` });
      await loadState();
    } catch (error) {
      notify({
        type: 'error',
        text: operationMessage(error, 'No se pudo registrar la revisión.'),
      });
    }
  };

  const submitMissing = async () => {
    if (!reviewResult?.token || !missingReason.trim() || !isDesktop) return;
    try {
      const receipt = await callInventory('/faltantes', {
        method: 'POST',
        body: {
          codigo: reviewResult.codigo,
          token: reviewResult.token,
          motivo: missingReason.trim(),
          clave: keyFor(`missing:${reviewResult.codigo}`),
        },
      });
      clearKey(`missing:${reviewResult.codigo}`);
      setLastReceipt({
        id: receipt.movimiento_id,
        codigo: reviewResult.codigo,
        delta: -Number(reviewResult.neto),
        motivo: missingReason.trim(),
      });
      setMissingReason('');
      setReviewResult(null);
      notify({
        type: 'success',
        text: `Faltante de ${reviewResult.codigo} confirmado.`,
      });
      await loadState();
    } catch (error) {
      notify({
        type: 'error',
        text: operationMessage(error, 'No se pudo confirmar el faltante.'),
      });
    }
  };

  const renderSession = () => {
    const readings = activeSession?.lecturas || [];
    return (
      <div className="mesa-inventory-columns">
        <section className="mesa-inventory-panel primary-panel">
          <div className="mesa-inventory-panel-heading">
            <div>
              <h2>Lectura continua C66</h2>
              <p>Escanee una manga y mantenga el foco en el lector.</p>
            </div>
            <span
              className={`mesa-inventory-status ${sessionId ? 'ready' : ''}`}
            >
              {sessionId ? 'Sesión activa' : 'Sin sesión'}
            </span>
          </div>
          <div className="mesa-inventory-form-grid">
            <label htmlFor="inventory-zone">
              Zona
              <select
                id="inventory-zone"
                value={zone}
                disabled={Boolean(sessionId)}
                onChange={(event) => setZone(event.target.value)}
              >
                <option value="" disabled>
                  Selecciona la zona
                </option>
                {state.zonas.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.nombre}
                  </option>
                ))}
              </select>
            </label>
            <div className="mesa-inventory-actions session-actions">
              {sessionId ? (
                <>
                  <span className="mesa-inventory-session-code">
                    {sessionId}
                  </span>
                  <label>
                    <input type="checkbox" checked={roomCovered} disabled={sessionBusy}
                      onChange={(event) => setRoomCovered(event.target.checked)} />
                    Ya recorrí toda esta habitación
                  </label>
                  <NoticeButton
                    secondary
                    onClick={closeSession}
                    disabled={sessionBusy}
                  >
                    Cerrar sesión
                  </NoticeButton>
                </>
              ) : (
                <>
                  <NoticeButton
                    onClick={createSession}
                    disabled={!zone || sessionBusy}
                  >
                    {sessionBusy ? 'Abriendo…' : 'Iniciar sesión C66'}
                  </NoticeButton>
                  {state.sesiones
                    .filter((item) => item.estado?.toUpperCase() === 'ABIERTA')
                    .map((item) => (
                      <NoticeButton
                        key={item.id}
                        secondary
                        onClick={() => resumeSession(item)}
                      >
                        Reanudar {item.id}
                      </NoticeButton>
                    ))}
                </>
              )}
            </div>
          </div>
          <form
            className="mesa-inventory-scan-form"
            onSubmit={scanSessionReading}
          >
            <label htmlFor="inventory-scan">Escanear QR de manga</label>
            <div>
              <input
                ref={scanRef}
                id="inventory-scan"
                disabled={!zone}
                value={scanner}
                onChange={(event) => setScanner(event.target.value)}
                autoComplete="off"
                placeholder="C66-..."
                autoFocus
              />
              <button
                type="submit"
                className="mesa-inventory-btn primary"
                disabled={!zone || !scanner.trim() || scanBusy}
              >
                Registrar lectura
              </button>
            </div>
            <small>
              Lectura continua · Enter agrega el código y devuelve el foco al
              lector.
            </small>
          </form>
          {sessionFeedback && (
            <p className="mesa-inventory-scan-feedback" role="status">
              {sessionFeedback}
            </p>
          )}
          {discrepancy && (
            <div className="mesa-inventory-discrepancy" role="alert">
              <strong>Confirma dónde encontraste la manga</strong>
              <span>
                {discrepancy.code} figura en{' '}
                {state.zonas.find((z) => z.id === discrepancy.previousZone)
                  ?.nombre || discrepancy.previousZone}
                .
              </span>
              <p>
                ¿La encontraste en <strong>{selectedZoneName}</strong>?
              </p>
              <NoticeButton onClick={acceptZoneDiscrepancy} disabled={scanBusy}>
                Sí, registrar en {selectedZoneName}
              </NoticeButton>
            </div>
          )}
          <div
            className="mesa-inventory-reading-list"
            aria-label="Lecturas de la sesión"
          >
            <h3>
              Lecturas capturadas <span>{readings.length}</span>
            </h3>
            {readings.length === 0 ? (
              <p className="mesa-inventory-empty">
                Aún no hay lecturas en esta sesión.
              </p>
            ) : (
              readings.map((reading) => (
                <div className="mesa-inventory-reading" key={reading.codigo}>
                  <strong>{reading.codigo}</strong>
                  <span>{articleNameForReading(reading)}</span>
                  <button
                    type="button"
                    className="mesa-inventory-link"
                    onClick={() => removeReading(reading.codigo)}
                    disabled={scanBusy}
                  >
                    Quitar captura
                  </button>
                </div>
              ))
            )}
          </div>
        </section>
        <aside className="mesa-inventory-secondary">
          <section className="mesa-inventory-panel">
            <h2>Manga sin identidad</h2>
            <p>
              Llévala a la estación de pesaje. Ahí se crea su identidad, se
              registra la zona donde fue encontrada y se completa el pesaje.
            </p>
          </section>
          <StateSummary state={state} />
        </aside>
      </div>
    );
  };

  const renderMesa = () => (
    <div className="mesa-inventory-columns">
      <section className="mesa-inventory-panel primary-panel">
        <div className="mesa-inventory-panel-heading">
          <div>
            <h2>Pesaje de pendientes</h2>
            <p>Escanee una identidad pendiente y confirme el neto con la balanza configurada.</p>
          </div>
          <span className={`mesa-inventory-scale ${accuraMode && scaleStatus.disponible ? 'ready' : ''}`}>⚖ {inventoryScaleLabel}</span>
        </div>
        <form className="mesa-inventory-scan-form" onSubmit={scanMesa}>
          <label htmlFor="mesa-inventory-scan">Escanear identidad</label>
          <div>
            <input
              ref={scanRef}
              id="mesa-inventory-scan"
              value={scanner}
              onChange={(event) => setScanner(event.target.value)}
              placeholder="MESA-..."
              autoComplete="off"
              autoFocus
            />
            <button
              type="submit"
              className="mesa-inventory-btn primary"
              disabled={!scanner.trim()}
            >
              Resolver QR
            </button>
          </div>
          <small>Puede escribir el código manualmente si no hay lector.</small>
        </form>
        {scaleStatusWarning && <div className="mesa-scale-warning-wrap"><p className="mesa-scale-warning" role="status">{scaleStatusWarning}</p><button type="button" className="mesa-inventory-btn secondary" onClick={() => refreshScaleStatus().catch(() => {})} disabled={scaleBusy || weighingBusy}>Reintentar estado de balanza</button></div>}
        <div
          className="mesa-inventory-pending-list"
          aria-label="Pendientes de pesaje"
        >
          <h3>Pendientes disponibles</h3>
          {state.pendientes.length === 0 ? (
            <p className="mesa-inventory-empty">
              No hay pendientes disponibles.
            </p>
          ) : (
            state.pendientes.map((item) => (
              <button
                type="button"
                className={`mesa-inventory-pending-row ${pending?.codigo === item.codigo ? 'selected' : ''}`}
                key={item.codigo}
                onClick={() => choosePending(item.codigo)}
              >
                <strong>{item.codigo}</strong>
                <span>
                  {articleNameForReading(item)} · {state.zonas.find((z) => z.id === item.zona)?.nombre}
                </span>
                <em>{item.neto ? `${item.neto} kg` : 'Sin pesar'}</em>
              </button>
            ))
          )}
        </div>
        {pending && !weighingResult && (
          <section
            className="mesa-inventory-weighing"
            aria-label={`Balanza ${accuraMode ? 'Accura' : 'manual'}`}
          >
            <div className="mesa-inventory-weight-display">
              <span>{accuraMode ? 'Bruto capturado · manga completa' : 'Neto calculado · entrada manual'}</span>
              <strong>
                {net !== null && net > 0 ? net.toFixed(3) : '—'}{' '}
                <small>kg</small>
              </strong>
            </div>
            <div className="mesa-inventory-form-grid">
              <label htmlFor="gross-weight">
                Peso bruto (kg)
                <input
                  id="gross-weight"
                  inputMode="decimal"
                  value={gross}
                  onChange={(event) => setGross(event.target.value)}
                  placeholder="0,000"
                  aria-describedby="inventory-weight-hint"
                  disabled={!manualMode || accuraMode}
                />
              </label>
              <label htmlFor="tare-weight">
                Tara (kg)
                <input
                  id="tare-weight"
                  inputMode="decimal"
                  value={tare}
                  onChange={(event) => setTare(event.target.value)}
                  placeholder="0,000"
                  aria-describedby="inventory-weight-hint"
                  disabled={!manualMode && !accuraMode}
                />
              </label>
            </div>
            <p id="inventory-weight-hint" className="mesa-inventory-hint">
              {accuraMode
                ? (scaleStatus.base === 'GS'
                  ? (scaleHasWeight ? 'Accura entrega bruto (GS); la tara se informa localmente una sola vez.' : (scaleStatus.mensaje || 'Accura conectada · espere estabilización y vuelva a leer'))
                  : 'Accura entrega NT. Confirme que la balanza está sin tara para tratar la lectura como bruto antes de descontar la tara local.')
                : 'Entrada manual explícita · use coma o punto, hasta 3 decimales. El neto debe ser mayor que 0.'}
            </p>
            {scaleStatusWarning && <p className="mesa-scale-warning" role="status">{scaleStatusWarning}</p>}
            {accuraMode && scaleStatus.base === 'NT' && (
              <label className="mesa-inventory-check">
                <input type="checkbox" checked={tareConfirmedForNt} onChange={(event) => setTareConfirmedForNt(event.target.checked)} />
                Confirmo que la balanza está sin tara; usaré esta lectura como peso bruto.
              </label>
            )}
            {accuraMode && (
              <div className="mesa-scale-capture-actions">
                <button type="button" className="mesa-inventory-btn secondary" onClick={() => refreshScaleStatus().catch(() => {})} disabled={scaleBusy || weighingBusy}>
                  Actualizar estado de balanza
                </button>
                <button id="scale-capture" type="button" className="mesa-inventory-btn secondary" onClick={captureInventoryWeight} disabled={!scaleStatus.disponible || scaleBusy || weighingBusy || (scaleStatus.base === 'NT' && !tareConfirmedForNt)}>
                  {scaleBusy ? 'Leyendo…' : gross ? 'Volver a leer balanza' : 'Leer balanza'}
                </button>
              </div>
            )}
            {((gross && !parseWeight(gross)) ||
              (tare && !parseWeight(tare)) ||
              (net !== null && net <= 0)) && (
              <p className="mesa-inventory-field-error" role="alert">
                Corrija el peso: use valores numéricos de hasta 3 decimales y un
                neto mayor que 0.
              </p>
            )}
            <NoticeButton
              onClick={registerWeighing}
              disabled={weighingBusy || scaleBusy || net === null || net <= 0 || (!manualMode && !accuraMode) || (accuraMode && (!gross || (scaleStatus.base === 'NT' && !tareConfirmedForNt)))}
            >
              {weighingBusy ? 'Registrando…' : 'Registrar pesaje'}
            </NoticeButton>
          </section>
        )}
        {weighingResult && (
          <section className="mesa-inventory-result">
            <strong>{weighingResult.codigo}</strong>
            <span>Neto confirmado por pesaje: {weighingResult.neto} kg</span>
            <span className="mesa-inventory-result-status">
              Estado: {confirmed ? 'confirmado' : 'pendiente de confirmación'}
            </span>
            {!lanMode && (
              <LabelPreview code={weighingResult.codigo} kind="pesaje" />
            )}
            <label
              className="mesa-inventory-reason"
              htmlFor="confirmation-reason"
            >
              Motivo de confirmación
              <textarea
                id="confirmation-reason"
                value={confirmationReason}
                onChange={(event) => setConfirmationReason(event.target.value)}
                placeholder="Motivo del ajuste de inventario"
              />
            </label>
            <span className="mesa-inventory-pc-only">
              Confirmación disponible solo en PC.
            </span>
            <NoticeButton
              onClick={confirmWeighing}
              disabled={!isDesktop || !confirmationReason.trim() || confirmed}
            >
              {confirmed ? 'Ingreso confirmado' : 'Confirmar ingreso'}
            </NoticeButton>
          </section>
        )}
      </section>
      <aside className="mesa-inventory-secondary">
        <section className="mesa-inventory-panel">
          <h2>Registrar manga sin identidad</h2>
          <p>
            Selecciona la zona donde fue encontrada y su pieza y color. La mesa
            genera el código y deja listo el pesaje de esa misma manga.
          </p>
          {reservedCode && (
            <div className="mesa-inventory-scan-feedback" role="status">
              <strong>{reservedCode}</strong> · se reutilizará esta etiqueta.
              <button
                type="button"
                className="mesa-inventory-link"
                onClick={() => setReservedCode('')}
              >
                Cancelar selección
              </button>
            </div>
          )}
          <form className="mesa-inventory-stack" onSubmit={createIndividual}>
            <label htmlFor="individual-zone">
              Zona
              <select
                id="individual-zone"
                value={zone}
                disabled={Boolean(sessionId)}
                onChange={(event) => setZone(event.target.value)}
              >
                <option value="" disabled>
                  Selecciona la zona
                </option>
                {state.zonas.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.nombre}
                  </option>
                ))}
              </select>
            </label>
            <label htmlFor="individual-article">
              Artículo
              <select
                id="individual-article"
                value={article}
                onChange={(event) => setArticle(event.target.value)}
              >
                <option value="" disabled>
                  Selecciona pieza y color
                </option>
                {state.articulos.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.nombre} · {item.color}
                  </option>
                ))}
              </select>
            </label>
            <NoticeButton type="submit" disabled={!zone || !article || createBusy}>
              {createBusy ? 'Creando identidad…' : 'Registrar manga sin identidad'}
            </NoticeButton>
          </form>
        </section>
        <StateSummary state={state} />
      </aside>
    </div>
  );

  const renderRevision = () => (
    <div className="mesa-inventory-columns revision-columns">
      <section className="mesa-inventory-panel primary-panel">
        <div className="mesa-inventory-panel-heading">
          <div>
            <h2>Revisión de faltantes</h2>
            <p>
              Separe la cobertura, movimientos y búsqueda antes de confirmar.
            </p>
          </div>
          <span className="mesa-inventory-pc-only">Solo PC</span>
        </div>
        <form className="mesa-inventory-stack" onSubmit={submitReview}>
          <label htmlFor="review-code">
            Código a revisar
            <input
              id="review-code"
              list="mangas-por-localizar"
              value={reviewCode}
              onChange={(event) => {
                setReviewCode(event.target.value);
                setReviewResult(null);
                setMissingReason('');
              }}
              placeholder="MESA-..."
            />
            <datalist id="mangas-por-localizar">
              {state.mangas
                .filter(
                  (manga) =>
                    ['DISPONIBLE', 'RECIBIDA'].includes(manga.estado) &&
                    !state.sesiones.some((sesion) =>
                      sesion.lecturas.some(
                        (lectura) => lectura.codigo === manga.codigo,
                      ),
                    ),
                )
                .map((manga) => (
                  <option key={manga.codigo} value={manga.codigo}>
                    {manga.neto} kg
                  </option>
                ))}
            </datalist>
          </label>
          <label htmlFor="review-search">
            Búsqueda de apoyo
            <input
              id="review-search"
              value={reviewSearch}
              onChange={(event) => setReviewSearch(event.target.value)}
              placeholder="Código, artículo o zona"
            />
          </label>
          <div className="mesa-inventory-checks">
            <label>
              <input
                type="checkbox"
                checked={reviewChecks.coverage}
                onChange={(event) => {
                  setReviewResult(null);
                  setReviewChecks((current) => ({
                    ...current,
                    coverage: event.target.checked,
                  }));
                }}
              />{' '}
              Cobertura revisada
            </label>
            <label>
              <input
                type="checkbox"
                checked={reviewChecks.movements}
                onChange={(event) => {
                  setReviewResult(null);
                  setReviewChecks((current) => ({
                    ...current,
                    movements: event.target.checked,
                  }));
                }}
              />{' '}
              Movimientos revisados
            </label>
            <label>
              <input
                type="checkbox"
                checked={reviewChecks.search}
                onChange={(event) => {
                  setReviewResult(null);
                  setReviewChecks((current) => ({
                    ...current,
                    search: event.target.checked,
                  }));
                }}
              />{' '}
              Búsqueda completada
            </label>
          </div>
          <NoticeButton
            type="submit"
            disabled={!isDesktop || !reviewCode.trim()}
          >
            Registrar revisión
          </NoticeButton>
        </form>
        {reviewResult && (
          <section className="mesa-inventory-result">
            <strong>Revisión {reviewResult.codigo}</strong>
            <span>
              Neto informado: {reviewResult.neto ?? 'no disponible'} kg
            </span>
            <label className="mesa-inventory-reason" htmlFor="missing-reason">
              Motivo del faltante
              <textarea
                id="missing-reason"
                value={missingReason}
                onChange={(event) => setMissingReason(event.target.value)}
                placeholder="Explique la diferencia encontrada"
              />
            </label>
            <NoticeButton
              onClick={submitMissing}
              disabled={!isDesktop || !missingReason.trim()}
            >
              Confirmar faltante
            </NoticeButton>
          </section>
        )}
      </section>
      <aside className="mesa-inventory-secondary">
        <section className="mesa-inventory-panel">
          <h2>Movimientos para consultar</h2>
          {filteredMovements.length === 0 ? (
            <p className="mesa-inventory-empty">
              No hay movimientos que coincidan.
            </p>
          ) : (
            <ul className="mesa-inventory-movement-list">
              {filteredMovements.map((item, index) => (
                <li key={item.id || item.codigo || index}>
                  <strong>{item.codigo || item.code || 'Movimiento'}</strong>
                  <span>
                    {item.tipo?.replaceAll('_', ' ')} · {item.delta} kg ·{' '}
                    {item.motivo}
                  </span>
                  <small>
                    AJ-{String(item.id).padStart(4, '0')}
                    {item.vinculo_baja
                      ? ` · Baja vinculada ${item.vinculo_baja}`
                      : ''}{' '}
                    · {new Date(item.created_at).toLocaleString('es-PE')}
                  </small>
                </li>
              ))}
            </ul>
          )}
        </section>
        <StateSummary state={state} />
      </aside>
    </div>
  );

  return (
    <section
      className="mesa-inventory app"
      aria-label="Inventario del módulo de pesaje"
    >
      <header className="header mesa-inventory-header">
        <div>
          <h1>
            {lanMode
              ? 'Inventario de piezas'
              : '⚖️ Sistema de Pesado - ENVAPERU'}
          </h1>

          {lanMode && <p>{selectedZoneName}</p>}
        </div>
        {!lanMode && (
          <div className="connection-badge">
            {loading ? 'Cargando inventario…' : inventoryScaleLabel}
          </div>
        )}
      </header>
      <main className="mesa-inventory-main">
        <div className="mesa-inventory-title-row">
          {!lanMode && <h2>{MODE_COPY[view].title}</h2>}
          <div className="mesa-inventory-actions">
            {loadFailed && (
              <NoticeButton secondary onClick={loadState}>
                Reintentar carga
              </NoticeButton>
            )}
            {!lanMode && (
              <NoticeButton secondary onClick={loadState} disabled={loading}>
                Actualizar estado
              </NoticeButton>
            )}
          </div>
        </div>
        {view === 'revision' && lastReceipt?.id && (
          <section className="mesa-inventory-result" role="status">
            <strong>
              Comprobante AJ-{String(lastReceipt.id).padStart(4, '0')}
            </strong>
            <span>
              {lastReceipt.codigo} · {Number(lastReceipt.delta) > 0 ? '+' : ''}
              {Number(lastReceipt.delta).toFixed(3)} kg · {lastReceipt.motivo}
            </span>
            {lastReceipt.vinculo_baja && (
              <span>Baja vinculada · {lastReceipt.vinculo_baja}</span>
            )}
          </section>
        )}
        {view === 'c66'
          ? renderSession()
          : view === 'mesa'
            ? renderMesa()
            : renderRevision()}
      </main>
      <MesaNotices notices={notices} dismiss={dismiss} />
    </section>
  );
}
