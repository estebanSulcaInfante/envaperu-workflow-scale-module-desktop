import { useEffect, useMemo, useRef, useState } from 'react';
import { scmWeighingApi } from '../services/api';

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
  const [controlCount, setControlCount] = useState('');
  const [controlReason, setControlReason] = useState('CAMBIO_TURNO');
  const [controlResult, setControlResult] = useState(null);
  const operationIdRef = useRef(null);
  const controlOperationIdRef = useRef(null);
  const online = centralState === 'ONLINE';
  const centralAvailable = online || simulationEnabled || portfolioDemoMode;
  const otContext = context?.manga?.ot;
  const colorWork = context?.manga?.trabajo_color;
  const currentMachinist = context?.manga?.asignacion_vigente?.maquinista
    || context?.manga?.maquinista
    || 'Sin asignación vigente';
  const tare = Number(context?.manga?.tara_nominal_kg || 0);
  const net = Math.max(0, Number(peso || 0) - tare);
  const validControl = Number(controlCount) > 0 && controlReason.trim().length > 0;
  const canConfirm = Boolean(
    context?.can_weigh
      && !result
      && !controlResult
      && listening
      && centralAvailable
      && Number(peso) > tare
      && !busy
      && !context?.demo_only,
  );
  const canRecordControl = Boolean(
    context?.can_register_shift_cut
      && !result
      && !controlResult
      && listening
      && centralAvailable
      && Number(peso) > tare
      && !busy
      && !context?.demo_only
      && validControl,
  );

  const resolveQr = async (requestedValue = qr) => {
    const requestedQr = typeof requestedValue === 'string' ? requestedValue : qr;
    if (!requestedQr.trim() || busy) return;
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const { data } = await scmWeighingApi.resolve(requestedQr.trim());
      setContext(data);
      setControlCount('');
      setControlReason('CAMBIO_TURNO');
      setControlResult(null);
      operationIdRef.current = null;
      controlOperationIdRef.current = null;
      setQr('');
    } catch (requestError) {
      setContext(null);
      setError(
        requestError.response?.data?.message
          || 'No se pudo resolver la etiqueta en central.',
      );
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!canConfirm) return;
    if (!operationIdRef.current) operationIdRef.current = newOperationId();
    setBusy(true);
    setError('');
    setControlResult(null);
    try {
      const { data } = await scmWeighingApi.confirm(
        context.scanned_label_id,
        operationIdRef.current,
      );
      setResult(data);
      setContext((previous) => ({
        ...previous,
        can_weigh: false,
        can_register_shift_cut: false,
        manga: {
          ...previous.manga,
          estado: data.confirmed.weighing.estado_manga,
        },
      }));
    } catch (requestError) {
      setError(
        requestError.response?.data?.message
          || 'No se confirmó el pesaje. F2 reutilizará la misma operación.',
      );
    } finally {
      setBusy(false);
    }
  };

  const recordControl = async () => {
    if (!canRecordControl) return;
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
        controlCount,
        controlReason.trim(),
      );
      setControlResult(data);
      setContext((previous) => ({
        ...previous,
        can_weigh: false,
        can_register_shift_cut: false,
        manga: {
          ...previous.manga,
          ...(data.manga || {}),
          estado: data.manga?.estado || 'CONTINUIDAD_PENDIENTE',
        },
      }));
      setControlCount('');
      setControlReason('CAMBIO_TURNO');
      controlOperationIdRef.current = null;
    } catch (requestError) {
      setError(
        requestError.response?.data?.message
          || 'No se registró el corte. El reintento reutilizará la misma operación.',
      );
    } finally {
      setBusy(false);
    }
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
      if (event.key === 'F2') {
        event.preventDefault();
        confirm();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [canConfirm, context, busy]);

  const printState = result?.print_result?.result;
  const printPreviewSrc = useMemo(() => {
    const svg = result?.print_result?.preview_svg;
    return svg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}` : '';
  }, [result]);
  const statusText = useMemo(() => {
    if (!centralAvailable) return 'Piloto SCM bloqueado: central sin conexión';
    if (!listening) return 'Conecte la balanza para capturar una lectura NET';
    if (!context) return 'Escanee el QR de PREPESAJE';
    if (controlResult) return 'Corte registrado · manga pendiente de continuidad';
    if (!context.can_weigh) return 'La manga ya no admite otro pesaje normal';
    if (Number(peso) <= tare) return 'Esperando peso bruto estable';
    return 'Lectura lista · Presione F2';
  }, [centralAvailable, listening, context, controlResult, peso, tare]);

  return (
    <div className="scm-weighing-layout">
      <section className="panel">
        <div className="panel-header">PESAJE SCM · MANGA PLANIFICADA</div>
        <div className="panel-body">
          <p className="scm-help">
            {portfolioDemoMode
              ? 'El QR carga el contexto. F2 toma la lectura virtual y genera una etiqueta final simulada.'
              : 'El QR resuelve todos los datos. F2 toma el peso de la balanza, confirma en central y despues imprime la etiqueta final.'}
          </p>
          {portfolioDemoMode && (
            <div className="portfolio-weighing-guide">
              <div>
                <strong>Recorrido sugerido</strong>
                <span>1. Carga la manga preparada.</span>
                <span>2. Aplica el peso simulado.</span>
                <span>3. Confirma con F2 y revisa la etiqueta.</span>
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
              autoFocus
              value={qr}
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
              disabled={!qr.trim() || busy || (!online && !simulationEnabled)}
              onClick={resolveQr}
            >
              Resolver
            </button>
          </div>
          {error && <div className="scm-message error">{error}</div>}
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
              <dl className="scm-context-grid">
              <div><dt>Manga</dt><dd>{context.manga.codigo}</dd></div>
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
                    <dd>{[colorWork.codigo, colorWork.color].filter(Boolean).join(' · ')}</dd>
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
              <div><dt>Pieza-color</dt><dd>{context.manga.pieza_color}</dd></div>
              <div><dt>Color</dt><dd>{context.manga.color || 'Sin color'}</dd></div>
              <div><dt>Tipo</dt><dd>{context.manga.tipo}</dd></div>
              <div>
                <dt>Cantidad confirmada por plan</dt>
                <dd>{context.manga.cantidad_asignada_un} un</dd>
              </div>
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
            <div><span>Neto físico</span><strong>{net.toFixed(3)} kg</strong></div>
          </div>
          {(context?.can_register_shift_cut || controlResult)
            && context?.manga?.tipo === 'NORMAL' && !context?.demo_only && (
            <div className="scm-simulation-box">
              <strong>Corte de turno · la manga continúa abierta</strong>
              <span>
                Registra el peso y conteo acumulados. No confirma producción, no crea inventario y no imprime.
              </span>
              <div className="scm-scan-row">
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={controlCount}
                  onChange={(event) => {
                    setControlCount(event.target.value);
                    controlOperationIdRef.current = null;
                  }}
                  placeholder="Conteo acumulado"
                  aria-label="Conteo acumulado de unidades"
                />
                <input
                  value={controlReason}
                  onChange={(event) => {
                    setControlReason(event.target.value);
                    controlOperationIdRef.current = null;
                  }}
                  placeholder="Motivo del control"
                  aria-label="Motivo del corte de turno"
                />
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={!canRecordControl}
                onClick={recordControl}
              >
                {busy ? 'Registrando corte…' : 'Registrar corte de turno — continúa abierta'}
              </button>
              {controlResult && (
                <div className="scm-message success">
                  <strong>Control de turno registrado</strong>
                  <span>
                    Manga abierta · QR preservado · producción confirmada 0 · sin inventario ni impresión.
                  </span>
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
          <div className={`scm-f2-state ${canConfirm ? 'ready' : ''}`}>
            {statusText}
          </div>
          <button
            className="btn btn-primary scm-f2-button"
            disabled={!canConfirm}
            onClick={confirm}
          >
            {busy ? 'Confirmando…' : 'Confirmar pesaje (F2)'}
          </button>
          {result && (
            <div className={`scm-result ${printState === 'IMPRESA' ? 'success' : 'warning'}`}>
              <strong>{result.portfolio_demo ? 'Pesaje demo confirmado' : 'Pesaje central confirmado'}</strong>
              <span>
                Neto {result.confirmed.weighing.peso_fisico_neto_kg} kg ·
                Producción OT {result.confirmed.weighing.kg_produccion_ot} kg
              </span>
              {result.confirmed.weighing.cantidad_confirmada != null && (
                <span>
                  Cantidad final {result.confirmed.weighing.cantidad_confirmada} un
                </span>
              )}
              {result.confirmed.atribucion_turnos?.length > 0 && (
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
