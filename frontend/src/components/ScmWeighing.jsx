import { useEffect, useMemo, useRef, useState } from 'react';
import { scmWeighingApi } from '../services/api';
import { getWeighingState, mangaStateLabel, needsPrintRetry } from '../utils/scmWeighingState';

const PORTFOLIO_DEMO_QR = JSON.stringify({
  v: 1,
  type: 'SCM_MANGA_LABEL',
  manga_id: '00000000-0000-4000-8000-000000000201',
  label_id: '00000000-0000-4000-8000-000000000101',
  label_type: 'PREPESAJE',
  label_version: 1,
});

function newOperationId() {
  return globalThis.crypto?.randomUUID?.()
    || '00000000-0000-4000-8000-000000000001';
}

const PENDING_PRINT_STORAGE_KEY = 'scm-weighing:pending-print:v1';
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function readPendingPrint() {
  try {
    const raw = globalThis.sessionStorage?.getItem(PENDING_PRINT_STORAGE_KEY);
    if (!raw) return null;
    const envelope = JSON.parse(raw);
    if (!envelope || envelope.version !== 1
      || !UUID_RE.test(envelope.operation_id || '')
      || !UUID_RE.test(envelope.scanned_label_id || '')
      || !envelope.context?.manga
      || envelope.context.scanned_label_id !== envelope.scanned_label_id
      || !needsPrintRetry(envelope.result)) {
      globalThis.sessionStorage?.removeItem(PENDING_PRINT_STORAGE_KEY);
      return null;
    }
    return envelope;
  } catch {
    try { globalThis.sessionStorage?.removeItem(PENDING_PRINT_STORAGE_KEY); } catch { /* fail closed */ }
    return null;
  }
}

function writePendingPrint(envelope) {
  try {
    const storage = globalThis.sessionStorage;
    if (!storage) return false;
    storage.setItem(PENDING_PRINT_STORAGE_KEY, JSON.stringify(envelope));
    return true;
  } catch {
    return false;
  }
}

function clearPendingPrint() {
  try {
    globalThis.sessionStorage?.removeItem(PENDING_PRINT_STORAGE_KEY);
  } catch {
    // The UI still reports the durable operation; storage cleanup is best effort.
  }
}

function normalizedColorToken(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .trim()
    .toUpperCase();
}

function validColorHex(value) {
  return /^#[0-9A-F]{6}$/i.test(String(value || '').trim())
    ? String(value).trim()
    : null;
}

export default function ScmWeighing({
  peso,
  listening,
  centralState,
  onConnect,
  simulationEnabled = false,
  onSimulateWeight,
  portfolioDemoMode = false,
}) {
  const [qr, setQr] = useState('');
  const [context, setContext] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [simulatedWeight, setSimulatedWeight] = useState('10.100');
  const [controlOnly, setControlOnly] = useState(false);
  const [closeConfirmationOpen, setCloseConfirmationOpen] = useState(false);
  const [scanConsumed, setScanConsumed] = useState(false);
  const [controlResult, setControlResult] = useState(null);
  const [contextNotice, setContextNotice] = useState('');
  const [imageFailed, setImageFailed] = useState(false);
  const operationIdRef = useRef(null);
  const controlOperationIdRef = useRef(null);
  const scannerInputRef = useRef(null);
  const closeCancelRef = useRef(null);
  const closeF2ReleasedRef = useRef(false);
  const requestInFlightRef = useRef(false);
  const restoredPendingRef = useRef(false);
  const online = centralState === 'ONLINE';
  const centralAvailable = online || simulationEnabled || portfolioDemoMode;
  const otContext = context?.manga?.ot;
  const colorWork = context?.manga?.trabajo_color;
  const isAssembly = Boolean(
    context?.manga?.oa_ot
      || context?.manga?.cantidad_fuente === 'RESPONSABLE_ARMADO',
  );
  const canonicalArticleKind = context?.manga?.articulo_clase === 'SUBENSAMBLE_WIP'
    ? 'WIP'
    : context?.manga?.articulo_clase === 'PRODUCTO_TERMINADO'
      ? 'Producto terminado'
      : null;
  const canonicalArticleIdentity = canonicalArticleKind
    ? [
        canonicalArticleKind,
        context?.manga?.articulo_codigo,
        context?.manga?.pieza_color,
      ].filter(Boolean).join(' · ')
    : null;
  const contentArticleIdentity = canonicalArticleIdentity
    || context?.manga?.pieza_color
    || context?.manga?.articulo_codigo;
  const colorIdentity = context?.manga?.color_identidad;
  const colorName = colorIdentity?.nombre
    || context?.manga?.color
    || colorWork?.color
    || 'Sin color';
  const colorHex = validColorHex(colorIdentity?.hex || context?.manga?.color_hex);
  const transparentColor = normalizedColorToken(
    colorIdentity?.familia?.nombre,
  ).includes('TRANSPARENTE');
  const currentMachinist = context?.manga?.asignacion_vigente?.maquinista
    || context?.manga?.maquinista
    || 'Sin asignación vigente';
  const tare = Number(context?.manga?.tara_nominal_kg || 0);
  const net = Math.max(0, Number(peso || 0) - tare);
  const continuitySnapshot = context?.continuidad ?? {};
  const hasLastControlKey = Object.prototype.hasOwnProperty.call(
    continuitySnapshot,
    'ultimo_control',
  );
  const closeDirect = Boolean(
    !controlOnly && context?.can_weigh && hasLastControlKey
      && continuitySnapshot.ultimo_control === null,
  );
  const lastControlNet = Number(controlResult?.control?.peso_neto_kg
    ?? context?.continuidad?.ultima_referencia_peso?.peso_neto_kg
    ?? context?.continuidad?.ultimo_control?.peso_neto_kg ?? 0);
  // Compare at the contract's gram precision so equal readings never render as -0.000 kg.
  const netDifference = (
    Math.round(net * 1000) - Math.round(lastControlNet * 1000)
  ) / 1000;
  const weighingState = getWeighingState({ context, busy, result, centralAvailable,
    listening, controlOnly, peso, tare, net,
    lastControlNet, validPartialClose: true,
    partialClose: false, error, scanConsumed });
  const canSubmit = weighingState.ready;
  const canConfirm = canSubmit && !controlOnly;
  const canRecordControl = canSubmit && controlOnly;
  const printRetry = needsPrintRetry(result);
  const controlAvailable = Boolean(context?.can_register_weight_control);
  const showIntentSelector = Boolean(
    !context?.demo_only
      && (context?.can_weigh || controlAvailable || controlResult),
  );

  const focusScanner = () => {
    window.setTimeout(() => scannerInputRef.current?.focus(), 0);
  };

  useEffect(() => {
    if (restoredPendingRef.current) return;
    restoredPendingRef.current = true;
    const pending = readPendingPrint();
    if (!pending) return;
    operationIdRef.current = pending.operation_id;
    setContext(pending.context);
    setResult(pending.result);
    setScanConsumed(false);
    setControlOnly(false);
    setError('Pesaje confirmado restaurado localmente; reintente solo la emision. No se releera la balanza.');
    setContextNotice('Se restauro una emision pendiente sin consultar nuevamente la balanza.');
  }, []);

  useEffect(() => {
    if (!printRetry || !context?.manga || !result || !operationIdRef.current) return;
    if (!writePendingPrint({
      version: 1,
      operation_id: operationIdRef.current,
      scanned_label_id: context.scanned_label_id,
      context,
      result,
    })) {
      setError('No se pudo conservar la emision pendiente en esta estacion; no cierres la pantalla antes de reintentar.');
    }
  }, [context, printRetry, result]);

  useEffect(() => {
    // Once the durable operation has reached any post-write/terminal result,
    // the old pre-emission envelope must not resurrect a duplicate retry.
    if (result && !needsPrintRetry(result)) clearPendingPrint();
  }, [result]);

  const resolveQr = async (requestedValue = qr) => {
    const requestedQr = typeof requestedValue === 'string' ? requestedValue : qr;
    if (!requestedQr.trim() || busy || requestInFlightRef.current || !centralAvailable || printRetry) return;
    requestInFlightRef.current = true;
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const { data } = await scmWeighingApi.resolve(requestedQr.trim());
      const previousCode = context?.manga?.codigo;
      const nextCode = data?.manga?.codigo;
      setContext(data);
      setControlOnly(false);
      setCloseConfirmationOpen(false);
      closeF2ReleasedRef.current = false;
      setScanConsumed(false);
      setControlResult(null);
      setImageFailed(false);
      setContextNotice(
        previousCode && previousCode !== nextCode
          ? `Cambio de manga confirmado: ${previousCode} → ${nextCode}`
          : `QR leído. Manga seleccionada: ${nextCode}`,
      );
      operationIdRef.current = null;
      controlOperationIdRef.current = null;
      setQr('');
    } catch (requestError) {
      setContext(null);
      setContextNotice('');
      setControlResult(null);
      setError(
        requestError.response?.data?.message
          || 'No se pudo resolver la etiqueta en central.',
      );
    } finally {
      requestInFlightRef.current = false;
      setBusy(false);
      focusScanner();
    }
  };

  const confirm = async () => {
    if ((!canConfirm && !printRetry) || requestInFlightRef.current || (printRetry && !operationIdRef.current)) return;
    const retryingPrint = printRetry;
    requestInFlightRef.current = true;
    if (!operationIdRef.current) operationIdRef.current = newOperationId();
    setBusy(true);
    setError('');
    setControlResult(null);
    try {
      const { data } = await scmWeighingApi.confirm(
        context.scanned_label_id,
        operationIdRef.current,
        {},
      );
      const retryAgain = needsPrintRetry(data);
      setResult(data);
      setScanConsumed(!retryAgain);
      if (retryAgain) {
        setError(data.print_result?.error || 'El pesaje quedo confirmado, pero la etiqueta no fue emitida.');
      }
      setCloseConfirmationOpen(false);
      setControlOnly(false);
      setContext((previous) => ({
        ...previous,
        can_weigh: false,
        can_register_shift_cut: false,
        can_register_weight_control: false,
        manga: {
          ...previous.manga,
          estado: data.confirmed.weighing.estado_manga,
        },
      }));
    } catch (requestError) {
      if (retryingPrint) {
        setError(requestError.response?.data?.message
          || 'No se pudo reemitir la etiqueta. El pesaje ya esta confirmado; conserva la misma operacion.');
        return;
      }
      setError(
        requestError.response?.data?.message
          || 'No se confirmó el pesaje. F2 reutilizará la misma operación.',
      );
    } finally {
      setCloseConfirmationOpen(false);
      requestInFlightRef.current = false;
      setBusy(false);
      focusScanner();
    }
  };

  const recordControl = async () => {
    if (!canRecordControl || requestInFlightRef.current) return;
    requestInFlightRef.current = true;
    if (!controlOperationIdRef.current) {
      controlOperationIdRef.current = newOperationId();
    }
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const { data } = await scmWeighingApi.control(
        context.scanned_label_id,
        controlOperationIdRef.current,
      );
      setControlResult(data);
      setScanConsumed(true);
      setContext((previous) => ({
        ...previous,
        can_weigh: true,
        can_register_weight_control: true,
        continuidad: { ...previous.continuidad, ultimo_control: data.control },
        manga: {
          ...previous.manga,
          ...(data.manga || {}),
          estado: data.manga?.estado || 'EN_LLENADO',
        },
      }));
      setControlOnly(false);
      controlOperationIdRef.current = null;
    } catch (requestError) {
      setError(
        requestError.response?.data?.message
          || 'No se registró el avance. El reintento reutilizará la misma operación.',
      );
    } finally {
      requestInFlightRef.current = false;
      setBusy(false);
      focusScanner();
    }
  };

  const submitWeighing = () => {
    if (!canSubmit) return;
    if (controlOnly) {
      recordControl();
      return;
    }
    if (closeDirect) {
      confirm();
      return;
    }
    closeF2ReleasedRef.current = false;
    setCloseConfirmationOpen(true);
  };

  const cancelCloseConfirmation = () => {
    if (busy) return;
    setCloseConfirmationOpen(false);
    closeF2ReleasedRef.current = false;
    setControlOnly(false);
    operationIdRef.current = null;
    focusScanner();
  };

  const simulateWeight = async () => {
    const value = Number(simulatedWeight);
    if (!Number.isFinite(value) || value <= 0 || busy) return;
    setBusy(true);
    setError('');
    try {
      await onSimulateWeight(value);
    } catch (requestError) {
      setError(
        requestError.response?.data?.error
          || 'No se pudo simular la lectura de balanza.',
      );
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape' && closeConfirmationOpen && !busy) {
        event.preventDefault();
        cancelCloseConfirmation();
        return;
      }
      if (event.key === 'F2') {
        event.preventDefault();
        if (event.repeat) return;
        if (closeConfirmationOpen) {
          if (busy || !closeF2ReleasedRef.current) return;
          closeF2ReleasedRef.current = false;
          confirm();
          return;
        }
        if (!canSubmit) return;
        submitWeighing();
      }
    };
    const onKeyUp = (event) => {
      if (event.key === 'F2' && closeConfirmationOpen) {
        closeF2ReleasedRef.current = true;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, [canSubmit, context, busy, controlOnly, closeConfirmationOpen,
    scanConsumed, closeDirect]);

  useEffect(() => {
    if (closeConfirmationOpen) closeCancelRef.current?.focus();
  }, [closeConfirmationOpen]);

  const printState = result?.print_result?.result;
  const controlPrintState = controlResult?.print_result?.result;
  const printPreviewSrc = useMemo(() => {
    const svg = result?.print_result?.preview_svg;
    return svg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}` : '';
  }, [result]);
  const controlPrintPreviewSrc = useMemo(() => {
    const svg = controlResult?.print_result?.preview_svg;
    return svg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}` : '';
  }, [controlResult]);

  return (
    <div className="scm-weighing-layout">
      <section className="panel">
        <div className="panel-header">PESAJE SCM · MANGA PLANIFICADA</div>
        <div className="panel-body">
          <p className="scm-help">
            {portfolioDemoMode
              ? 'El QR carga el contexto. F2 prepara el cierre final; marque Solo control de peso únicamente si la manga continuará abierta.'
              : 'Escanea la preetiqueta y revisa el estado. F2 prepara el cierre final; el control de peso es una excepción explícita.'}
          </p>
          {portfolioDemoMode && (
            <div className="portfolio-weighing-guide">
              <div>
                <strong>Recorrido sugerido</strong>
                <span>1. Carga la manga preparada.</span>
                <span>2. Aplica el peso simulado.</span>
                <span>3. F2 prepara el cierre; marque Solo control de peso si la manga continuará abierta.</span>
              </div>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy}
                onClick={() => resolveQr(PORTFOLIO_DEMO_QR)}
              >
                Cargar manga demo
              </button>
            </div>
          )}
          {!listening && (
            <button className="btn btn-primary" onClick={onConnect}>
              Conectar balanza
            </button>
          )}
          <div className="scm-scan-row">
            <input
              ref={scannerInputRef}
              autoFocus
              value={qr}
              disabled={busy || printRetry}
              onChange={(event) => setQr(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  resolveQr();
                }
              }}
              placeholder="Escanear QR de etiqueta PREPESAJE"
              aria-label="QR de manga SCM"
            />
            <button
              className="btn btn-primary"
              disabled={!qr.trim() || busy || printRetry || (!online && !simulationEnabled)}
              onClick={resolveQr}
            >
              Resolver
            </button>
          </div>
          {error && <div className="scm-message error" role="alert">{error}</div>}
          <div className="sr-only" role="status" aria-live="polite">
            {contextNotice}
          </div>
          {context && (
            <>
              {context.demo_only && (
                <div className="scm-message warning">
                  QR DEMO LOCAL: permite revisar contexto y peso simulado, pero nunca confirma ni imprime.
                </div>
              )}
              {context.portfolio_demo && (
                <div className="scm-message info">
                  Contexto sintetico del piloto. La confirmacion y la impresion permanecen aisladas.
                </div>
              )}
              <div className={`scm-active-manga ${context.can_weigh || context.can_register_weight_control ? '' : 'unavailable'}`} aria-label="Contexto de manga seleccionada">
                <div>
                  <span>MANGA SELECCIONADA</span>
                  <strong>{context.manga.codigo}</strong>
                  <b className="scm-manga-state">{mangaStateLabel(context.manga.estado)}</b>
                  <small>{contextNotice}</small>
                </div>
                {context.manga.imagen_url && !imageFailed && (
                  <img
                    src={context.manga.imagen_url}
                    alt="Pieza de la manga activa"
                    onError={() => setImageFailed(true)}
                  />
                )}
                {(!context.manga.imagen_url || imageFailed) && (
                  <div className="scm-piece-photo-fallback">
                    Sin foto registrada
                  </div>
                )}
              </div>
              {contentArticleIdentity && (
                <div className="scm-article-identity" aria-label="Artículo a pesar">
                  <span>Identidad del contenido</span>
                  <strong>{contentArticleIdentity}</strong>
                  <div className="scm-color-identity">
                    <span
                      className={`scm-color-swatch ${transparentColor ? 'transparent' : colorHex ? 'solid' : 'unknown'}`}
                      style={colorHex && !transparentColor
                        ? { '--scm-color-swatch': colorHex }
                        : undefined}
                      role="img"
                      aria-label={transparentColor
                        ? 'Muestra de color transparente'
                        : `Muestra de color ${colorName}`}
                    />
                    <div>
                      <small>Color</small>
                      <b>{colorName}</b>
                    </div>
                  </div>
                </div>
              )}
              <dl className="scm-context-grid">
              {otContext ? (
                <div>
                  <dt>OT / máquina / turno</dt>
                  <dd>{[otContext.codigo, otContext.maquina, otContext.turno].filter(Boolean).join(' · ')}</dd>
                </div>
              ) : (
                <div><dt>OF / OT</dt><dd>{context.manga.op_ot}</dd></div>
              )}
              {colorWork && (
                <>
                  <div>
                    <dt>Trabajo de color</dt>
                    <dd>{[colorWork.codigo, colorName].filter(Boolean).join(' · ')}</dd>
                  </div>
                  <div>
                    <dt>OF / corrida</dt>
                    <dd>{[
                      colorWork.orden_fabricacion,
                      colorWork.corrida,
                    ].filter(Boolean).join(' · ')}</dd>
                  </div>
                </>
              )}
              <div><dt>Fecha OT</dt><dd>{context.manga.fecha_operativa}</dd></div>
              <div><dt>Maquinista asignado</dt><dd>{currentMachinist}</dd></div>
              {!contentArticleIdentity && (
                <div>
                  <dt>{isAssembly ? 'Artículo armado' : 'Pieza-color'}</dt>
                  <dd>{context.manga.pieza_color}</dd>
                </div>
              )}
              <div><dt>Tipo</dt><dd>{context.manga.tipo}</dd></div>
              {isAssembly ? (
                <div>
                  <dt>Cantidad confirmada por Armado</dt>
                  <dd>{context.manga.cantidad_asignada_un} un</dd>
                </div>
              ) : (
                <div>
                  <dt>Peso fabricado teórico</dt>
                  <dd>{context.manga.peso_fabricado_teorico_kg == null
                    ? 'No disponible'
                    : `${Number(context.manga.peso_fabricado_teorico_kg).toFixed(3)} kg`}</dd>
                </div>
              )}
              </dl>
            </>
          )}
        </div>
      </section>
      <section className="panel">
        <div className="panel-header">LECTURA DE BALANZA</div>
        <div className="panel-body">
          <div
            className={`scm-live-weight ${listening ? 'connected' : 'disconnected'}`}
            data-testid="scm-current-weight"
            aria-label={`Peso actual de balanza: ${Number(peso).toFixed(3)} kilogramos`}
          >
            <span className="scm-live-weight-label">Peso actual de balanza</span>
            <div className="scm-live-weight-reading">
              <strong>{Number(peso).toFixed(3)}</strong>
              <span>kg</span>
            </div>
            <small>{listening ? 'Lectura en vivo' : 'Balanza desconectada'}</small>
          </div>
          <div className="scm-weight-grid scm-weight-breakdown">
            <div><span>Tara</span><strong>{tare.toFixed(3)} kg</strong></div>
            <div>
              <span>{isAssembly ? 'Peso neto total de Armado (kg)' : 'Peso neto real (kg)'}</span>
              <strong>{net.toFixed(3)} kg</strong>
            </div>
            {!isAssembly && (
              <>
                <div>
                  <span>Último NET aceptado</span>
                  <strong>{lastControlNet.toFixed(3)} kg</strong>
                </div>
                <div>
                  <span>Diferencia</span>
                  <strong>{netDifference.toFixed(3)} kg</strong>
                </div>
              </>
            )}
          </div>
          {showIntentSelector && (
            <div className={`scm-control-mode ${controlOnly ? 'control' : context?.can_weigh ? 'closing' : 'required'}`}>
              <div className="scm-intent-current" aria-live="polite">
                <strong>
                  {controlOnly
                    ? 'CONTROL DE PESO'
                    : context?.can_weigh ? 'CIERRE FINAL' : 'CONTROL DE PESO REQUERIDO'}
                </strong>
                <span>
                  {controlOnly
                    ? 'Excepción seleccionada · la manga continuará abierta.'
                    : context?.can_weigh
                      ? closeDirect
                        ? 'Sin control previo registrado · F2 cerrará directamente la manga.'
                        : 'Control previo o historial desconocido · F2 abre una guarda antes de cerrar.'
                      : 'Esta manga no admite cierre final; seleccione el control para habilitar F2.'}
                </span>
              </div>
              <label>
                <input
                  type="checkbox"
                  checked={controlOnly}
                  disabled={scanConsumed || !controlAvailable || busy || Boolean(error && (operationIdRef.current || controlOperationIdRef.current))}
                  onChange={(event) => {
                    setControlOnly(event.target.checked);
                  }}
                  aria-label="Solo control de peso"
                />
                <span>
                  <strong>Solo control de peso</strong>
                  Marcar únicamente si la manga continuará abierta
                </span>
              </label>
              <span>
                {controlOnly
                  ? 'Solo kg. No cambia maquinista, turno ni OT; no crea inventario.'
                  : context?.can_weigh
                    ? closeDirect
                      ? 'Sin control previo registrado. F2 cerrará directamente la manga.'
                      : 'Control previo o historial desconocido. F2 abre la guarda; suelte y pulse F2 nuevamente para confirmar.'
                    : 'F2 permanecerá bloqueado hasta seleccionar el control de peso.'}
              </span>
              {controlResult && (
                <div className="scm-message success">
                  <strong>Avance en kg registrado</strong>
                  <span>
                    Peso neto real {controlResult.control?.peso_neto_kg} kg · aporte desde control anterior {controlResult.control?.aporte_desde_control_anterior_kg} kg.
                  </span>
                  <span>
                    Manga abierta · QR de preetiqueta preservado · sin conteo · impresión {controlPrintState || 'pendiente'}.
                  </span>
                  {controlPrintPreviewSrc && (
                    <figure className="portfolio-postlabel-preview">
                      <img src={controlPrintPreviewSrc} alt="Sticker de control sin QR" />
                      <figcaption>CONTROL · sin QR · conservar preetiqueta</figcaption>
                    </figure>
                  )}
                </div>
              )}
            </div>
          )}
          {simulationEnabled && (
            <div className="scm-simulation-box">
              <strong>
                {portfolioDemoMode ? 'Dispositivo virtual // RS-232' : 'Modo local · balanza simulada'}
              </strong>
              <span>
                {portfolioDemoMode
                  ? 'La lectura reproduce el contrato de la balanza sin acceder a un puerto fisico.'
                  : 'Permite probar la estación sin un equipo conectado. No habilitar en planta.'}
              </span>
              <div className="scm-scan-row">
                <input
                  type="number"
                  min="0.001"
                  step="0.001"
                  value={simulatedWeight}
                  onChange={(event) => setSimulatedWeight(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') simulateWeight();
                  }}
                  aria-label="Peso simulado en kilogramos"
                />
                <button
                  className="btn btn-secondary"
                  disabled={busy || Number(simulatedWeight) <= 0}
                  onClick={simulateWeight}
                >
                  Aplicar peso simulado
                </button>
              </div>
            </div>
          )}
          <div id="scm-weighing-state" className={`scm-f2-state ${weighingState.kind}`} aria-live="polite" aria-atomic="true">
            <strong>{weighingState.title}</strong>
            <span>{!controlOnly && closeDirect
              ? 'F2 cerrará directamente esta manga sin diálogo.'
              : !controlOnly && weighingState.ready
                ? 'Primer F2 abre la guarda; suelte y pulse F2 nuevamente para confirmar.'
                : weighingState.recovery}
            </span>
          </div>
          <button
            className="btn btn-primary scm-f2-button"
            disabled={!canSubmit}
            aria-describedby="scm-weighing-state"
            onClick={submitWeighing}
          >
            {busy ? 'Registrando…' : 'Pesar manga (F2)'}
          </button>
          {closeConfirmationOpen && (
            <div className="scm-close-dialog-backdrop">
              <div
                className="scm-close-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby="scm-close-dialog-title"
                aria-describedby="scm-close-dialog-description"
              >
                <span className="scm-close-dialog-kicker">ACCIÓN FINAL</span>
                <h2 id="scm-close-dialog-title">Confirmar cierre final</h2>
                <strong className="scm-close-dialog-manga">
                  {context?.manga?.codigo}
                </strong>
                <div className="scm-close-dialog-net">
                  <span>Peso neto real</span>
                  <strong>{net.toFixed(3)} kg</strong>
                </div>
                <p id="scm-close-dialog-description">
                  No es un control de peso. La manga quedará cerrada, dejará de
                  admitir nuevos pesos y se generará el comprobante final.
                </p>
                <p className="scm-close-dialog-recovery">
                  Si la manga continuará llenándose, cancele y marque Solo control de peso.
                </p>
                <div className="scm-close-dialog-actions">
                  <button
                    ref={closeCancelRef}
                    type="button"
                    className="btn btn-secondary"
                    disabled={busy}
                    onClick={cancelCloseConfirmation}
                  >
                    Cancelar; revisar intención
                  </button>
                  <button
                    type="button"
                    className="btn scm-close-confirm-button"
                    disabled={busy}
                    onClick={confirm}
                  >
                    {busy ? 'Cerrando…' : 'Confirmar cierre de manga'}
                  </button>
                </div>
                <small>F2 confirma solo después de soltar la tecla; también puede usar el botón explícito.</small>
              </div>
            </div>
          )}
          {result && (
            <div className={`scm-result ${printState === 'IMPRESA' ? 'success' : 'warning'}`}>
              <strong>{result.portfolio_demo ? 'Pesaje demo confirmado' : 'Pesaje central confirmado'}</strong>
              {isAssembly ? (
                <span>
                  Neto total de Armado {result.confirmed.weighing.peso_fisico_neto_kg} kg
                </span>
              ) : (
                <span>
                  Peso neto real {result.confirmed.weighing.peso_fisico_neto_kg} kg ·
                  Peso fabricado teórico {result.confirmed.weighing.kg_produccion_ot} kg
                </span>
              )}
              {isAssembly && result.confirmed.weighing.cantidad_confirmada != null && (
                <span>
                  Cantidad final {result.confirmed.weighing.cantidad_confirmada} un
                </span>
              )}
              {isAssembly && result.confirmed.atribucion_turnos?.length > 0 && (
                <div className="scm-shift-attribution">
                  <strong>Atribución por turno</strong>
                  <ul>
                    {result.confirmed.atribucion_turnos.map((segment) => (
                      <li key={segment.id}>
                        {[segment.maquinista, segment.ot_codigo]
                          .filter(Boolean).join(' · ')}: {' '}
                        {segment.cantidad_atribuida_un} un
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <span>Etiqueta final: {printState}</span>
              {printRetry && (
                <>
                  <strong>El pesaje esta confirmado; la etiqueta no fue emitida.</strong>
                  <span>No se releera la balanza ni se creara otro pesaje.</span>
                  {result.print_result?.error && <small>{result.print_result.error}</small>}
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy}
                    onClick={confirm}
                  >
                    Reintentar solo emisi�n
                  </button>
                </>
              )}
              <small>
                Estado inventario: NO_INGRESADA · pendiente de recepción
              </small>
              {printPreviewSrc && (
                <figure className="portfolio-postlabel-preview">
                  <img src={printPreviewSrc} alt="Etiqueta TSC final simulada" />
                  <figcaption>Salida TSC simulada // POSTPESAJE</figcaption>
                </figure>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
