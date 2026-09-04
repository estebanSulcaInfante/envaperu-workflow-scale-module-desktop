import { useEffect, useRef, useState } from 'react';


export default function ScmInventoryOpening({ peso, listening, simulationEnabled, onSimulateWeight }) {
  const [targetQr, setTargetQr] = useState('');
  const [context, setContext] = useState(null);
  const [sessionUnits, setSessionUnits] = useState([]);
  const [tare, setTare] = useState('0.000');
  const [simulated, setSimulated] = useState('25.100');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [previewSvg, setPreviewSvg] = useState('');
  const [labelBusy, setLabelBusy] = useState(false);
  const [labelMessage, setLabelMessage] = useState(null);
  const [message, setMessage] = useState('Escanea o pega el contexto QR de la jornada física.');
  const inputRef = useRef(null);

  const requestLabel = async (unit, action = 'preview') => {
    if (!unit || labelBusy) return;
    setResult(unit);
    if (action === 'preview') setPreviewSvg('');
    setLabelBusy(true);
    setLabelMessage(null);
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (action === 'print') headers['Idempotency-Key'] = crypto.randomUUID();
      const response = await fetch(`/api/local/v1/scm/inventory-opening/labels/${action}`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ unit }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || payload.code || 'No se pudo preparar el sticker');
      if (payload.preview_svg) setPreviewSvg(payload.preview_svg);
      if (action === 'preview') {
        setLabelMessage({ type: 'info', text: 'Vista previa generada desde el mismo layout TSPL. Previsualizar no imprime.' });
      } else if (payload.result === 'SIMULADA') {
        setLabelMessage({ type: 'info', text: 'Impresión aceptada en simulación local; no se envió al spooler físico.' });
      } else if (payload.result === 'IMPRESA') {
        setLabelMessage({ type: 'success', text: `Sticker TSPL enviado a ${payload.printer_name || 'la impresora configurada'}.` });
      } else {
        setLabelMessage({ type: 'error', text: payload.error || `Resultado de impresión: ${payload.result}.` });
      }
    } catch (error) {
      setLabelMessage({ type: 'error', text: error.message });
    } finally {
      setLabelBusy(false);
    }
  };

  const resolveContext = async () => {
    try {
      const payload = JSON.parse(targetQr.trim());
      if (payload.type !== 'SCM_INVENTORY_OPENING_TARGET' || payload.v !== 1) {
        throw new Error('El QR no corresponde al módulo Inventario.');
      }
      if (!payload.opening_id || !payload.material_scm_id || !payload.ubicacion_codigo) {
        throw new Error('El contexto de apertura está incompleto.');
      }
      setBusy(true);
      setMessage('Validando jornada en Central…');
      const response = await fetch('/api/local/v1/scm/inventory-opening/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_qr: targetQr.trim() }),
      });
      const resolved = await response.json();
      if (!response.ok) throw new Error(resolved.message || resolved.code || 'Contexto rechazado');
      setContext(resolved);
      setSessionUnits(resolved.unidades_logisticas || []);
      setResult(null);
      setPreviewSvg('');
      setLabelMessage(null);
      setMessage(`Contexto aceptado: ${resolved.material_nombre} en ${resolved.ubicacion_codigo}. Coloca una bolsa y confirma con F2.`);
    } catch (error) {
      setContext(null);
      setSessionUnits([]);
      setResult(null);
      setPreviewSvg('');
      setLabelMessage(null);
      setMessage(error instanceof SyntaxError ? 'No se reconoció un QR de contexto válido.' : error.message);
    } finally {
      setBusy(false);
    }
  };

  const capture = async () => {
    if (!context || busy || labelBusy) return;
    setBusy(true); setMessage('Confirmando el peso estable en Central…');
    try {
      const response = await fetch('/api/local/v1/scm/inventory-opening/capture', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ target_qr: targetQr.trim(), tara_kg: tare }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || payload.code || 'Captura rechazada');
      setResult(payload.unidad);
      setSessionUnits((payload.opening?.unidades_logisticas || []).filter((unit) => (
        Number(unit.material_scm_id) === Number(context.material_scm_id)
        && unit.ubicacion_codigo === context.ubicacion_codigo
        && unit.estado_calidad === context.estado_calidad
      )));
      setMessage(`Bolsa ${payload.unidad.codigo} registrada. Imprime y pega su QR antes de retirarla.`);
      await requestLabel(payload.unidad, 'preview');
      inputRef.current?.focus();
    } catch (error) {
      setMessage(error.message);
    } finally { setBusy(false); }
  };

  useEffect(() => {
    const handler = (event) => {
      if (event.key === 'F2') { event.preventDefault(); capture(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  });

  return (
    <div className="scm-weighing-layout">
      <section className="panel">
        <div className="panel-header">APERTURA FÍSICA · CONTEXTO</div>
        <div className="panel-body">
          <p>Escanea el contexto y presiona Enter. La estación mostrará la sesión antes de permitir el pesaje; el escaneo por sí solo no cambia el Kardex.</p>
          <textarea ref={inputRef} rows="3" value={targetQr} onChange={(event) => { setTargetQr(event.target.value); setContext(null); setSessionUnits([]); setResult(null); setPreviewSvg(''); setLabelMessage(null); setMessage('Presiona Enter para validar el contexto.'); }} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); resolveContext(); } }} placeholder="Escanear o pegar QR de apertura física y presionar Enter" style={{ width: '100%' }} />
          {context && <section className="scm-active-material" aria-label="Material activo">
            <span>MATERIAL ACTIVO</span>
            <strong>{context.material_nombre || 'Material seleccionado'}</strong>
            <code>{context.material_codigo || `#${context.material_scm_id}`}</code>
            <div><small>{context.unidad_medida || 'KG'}</small><small>{context.ubicacion_codigo}</small><small>{String(context.estado_calidad || 'PENDIENTE').replaceAll('_', ' ')}</small></div>
          </section>}
          {context && <dl className="scm-context-grid scm-opening-context" aria-label="Contexto de apertura activo">
            <div><dt>JORNADA ACTIVA</dt><dd>{context.opening_codigo || String(context.opening_id).slice(0, 8)}</dd></div>
            <div><dt>UBICACIÓN</dt><dd>{context.ubicacion_codigo}</dd></div>
            <div><dt>CALIDAD</dt><dd>{String(context.estado_calidad || 'PENDIENTE').replaceAll('_', ' ')}</dd></div>
          </dl>}
          <label htmlFor="opening-tare">Tara del saco / contenedor (kg)</label>
          <input id="opening-tare" type="number" min="0" step="0.001" value={tare} onChange={(event) => setTare(event.target.value)} />
          <div className="scm-message info" role="status">{message}</div>
          <button className="btn btn-primary" disabled={!context || busy || labelBusy} onClick={capture}>Registrar bolsa (F2)</button>
          {context && <section className="scm-session-weighings" aria-label="Pesajes de la jornada">
            <header>
              <div><span>PESAJES DE LA JORNADA</span><strong>{sessionUnits.length} bolsa(s)</strong></div>
              <div><span>NET ACUMULADO</span><strong>{sessionUnits.reduce((sum, unit) => sum + Number(unit.peso_neto_kg || 0), 0).toFixed(3)} kg</strong></div>
            </header>
            {sessionUnits.length > 0 ? <div className="scm-session-table-wrap"><table>
              <thead><tr><th>#</th><th>Bolsa</th><th>Bruto</th><th>Tara</th><th>NET</th><th>Hora</th><th></th></tr></thead>
              <tbody>{sessionUnits.map((unit, index) => <tr key={unit.id}>
                <td>{index + 1}</td><td><strong>{unit.codigo}</strong></td><td>{Number(unit.peso_bruto_kg).toFixed(3)}</td><td>{Number(unit.tara_kg).toFixed(3)}</td><td><strong>{Number(unit.peso_neto_kg).toFixed(3)} kg</strong></td><td>{unit.created_at ? new Date(unit.created_at).toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' }) : '—'}</td><td><button className="btn btn-small" disabled={labelBusy} aria-label={`Ver sticker ${unit.codigo}`} onClick={() => requestLabel(unit, 'preview')}>Ver sticker</button></td>
              </tr>)}</tbody>
            </table></div> : <p className="scm-session-empty">La primera bolsa registrada aparecerá aquí sin cambiar de pantalla.</p>}
          </section>}
        </div>
      </section>
      <section className="panel">
        <div className="panel-header">LECTURA Y STICKER QR</div>
        <div className="panel-body">
          <div className="weight-display"><span>PESO BRUTO ACTUAL</span><strong>{Number(peso || 0).toFixed(3)} kg</strong><small>{listening ? 'Lectura en vivo' : 'Balanza desconectada'}</small></div>
          {simulationEnabled && <div className="simulation-panel"><strong>Modo local · balanza simulada</strong><div><input value={simulated} onChange={(event) => setSimulated(event.target.value)} /><button className="btn" onClick={() => onSimulateWeight(simulated)}>Aplicar peso simulado</button></div></div>}
          {result && <section className="scm-preview-section scm-opening-label-preview">
            <h3>Sticker TSPL de unidad logística</h3>
            {previewSvg ? <figure className="scm-render-preview">
              <img src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(previewSvg)}`} alt={`Vista previa TSPL de la unidad ${result.codigo}`} />
              <figcaption>Layout TSPL real · 109 × 50 mm · 203 DPI · QR {result.qr_value}</figcaption>
            </figure> : <p>{labelBusy ? 'Generando vista previa TSPL…' : 'Selecciona nuevamente el sticker para generar la vista previa.'}</p>}
            <div className="sr-only">Unidad {result.codigo}. QR {result.qr_value}. NET {result.peso_neto_kg} kg.</div>
            {labelMessage && <div className={`scm-message ${labelMessage.type}`} role="status" aria-live="polite">{labelMessage.text}</div>}
            <button className="btn btn-primary" disabled={labelBusy || !previewSvg} aria-label="Imprimir sticker TSPL" onClick={() => requestLabel(result, 'print')}>{labelBusy ? 'Procesando…' : 'Imprimir sticker TSPL'}</button>
          </section>}
        </div>
      </section>
    </div>
  );
}
