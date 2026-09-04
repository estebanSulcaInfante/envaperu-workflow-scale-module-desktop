import { useEffect, useRef, useState } from 'react';


export default function ScmPreparedMaterialWeighing({ peso, listening, simulationEnabled, onSimulateWeight }) {
  const [targetQr, setTargetQr] = useState('');
  const [context, setContext] = useState(null);
  const [tare, setTare] = useState('0.120');
  const [simulated, setSimulated] = useState('25.120');
  const [sourceQr, setSourceQr] = useState('');
  const [sourceQrs, setSourceQrs] = useState([]);
  const [sourceUnits, setSourceUnits] = useState([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [message, setMessage] = useState('Escanea el contexto de aporte o salida generado por la OPM.');
  const inputRef = useRef(null);

  const resolveContext = () => {
    try {
      const payload = JSON.parse(targetQr.trim());
      if (payload.type !== 'SCM_PREPARATION_WEIGHT_TARGET' || payload.v !== 1) {
        throw new Error('El QR no corresponde al módulo Preparación.');
      }
      if (!payload.orden_preparacion_id || !['APORTE', 'BOLSA_SALIDA'].includes(payload.tipo_uso)) {
        throw new Error('El contexto de preparación está incompleto.');
      }
      setContext(payload);
      setSourceQrs([]);
      setSourceUnits([]);
      setResult(null);
      setMessage(payload.tipo_uso === 'APORTE'
        ? 'Contexto aceptado. Escanea ahora cada bolsa de materia prima; F2 registrará el aporte.'
        : 'Contexto aceptado. Coloca la bolsa preparada en la balanza y confirma con F2.');
    } catch (error) {
      setContext(null);
      setMessage(error instanceof SyntaxError ? 'No se reconoció un QR de contexto válido.' : error.message);
    }
  };

  const acceptSourceQr = async () => {
    const value = sourceQr.trim();
    if (!value) return;
    if (!value.startsWith('SCM:UL:')) {
      setMessage('Este escaneo no es una bolsa de inventario SCM:UL.');
      return;
    }
    if (sourceQrs.includes(value)) {
      setMessage('Esa bolsa ya fue escaneada; no se añadió dos veces.');
      setSourceQr('');
      return;
    }
    setBusy(true);
    setMessage('Validando bolsa origen en Central…');
    try {
      const response = await fetch('/api/local/v1/scm/prepared-material/source-units/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_qr: targetQr.trim(), source_qr: value }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || payload.code || 'Bolsa rechazada');
      setSourceQrs((current) => [...current, value]);
      setSourceUnits((current) => [...current, payload]);
      setSourceQr('');
      setMessage(`Bolsa ${payload.codigo} aceptada. F2 aún no fue presionado: no se reservó ni consumió material.`);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  };

  const capture = async () => {
    if (!context || busy || (context.tipo_uso === 'APORTE' && sourceQrs.length === 0)) return;
    setBusy(true); setMessage('Registrando lectura estable…');
    try {
      const response = await fetch('/api/local/v1/scm/prepared-material/capture', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({
          target_qr: (() => {
            try {
              const parsed = JSON.parse(targetQr.trim());
              if (parsed.tipo_uso === 'APORTE') parsed.unidades_origen_qr = sourceQrs;
              return JSON.stringify(parsed);
            } catch { return targetQr.trim(); }
          })(),
          tara_kg: tare,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || payload.code || 'Captura rechazada');
      setResult(payload);
      setMessage('Lectura creada con evidencia de estación. Otro actor debe confirmarla antes de incorporarla o cerrar el lote.');
      inputRef.current?.focus();
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    const handler = (event) => { if (event.key === 'F2') { event.preventDefault(); capture(); } };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  });

  return <div className="scm-weighing-layout">
    <section className="panel"><div className="panel-header">PREPARACIÓN · PESAJE CONECTADO</div><div className="panel-body">
      <p>Primero escanea el contexto OPM y presiona Enter. Después, si es un aporte, escanea una por una las bolsas origen. Ningún escaneo consume material: F2 confirma el pesaje.</p>
      <textarea ref={inputRef} rows="3" value={targetQr} onChange={(event) => { setTargetQr(event.target.value); setContext(null); setSourceQrs([]); setSourceUnits([]); setMessage('Presiona Enter para validar el contexto OPM.'); }} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); resolveContext(); } }} placeholder="Escanear contexto QR de la OPM y presionar Enter" style={{ width: '100%' }} />
      {context && <dl className="scm-context-grid" aria-label="Contexto OPM activo">
        <div><dt>OPM</dt><dd>{context.orden_preparacion_codigo || String(context.orden_preparacion_id).slice(0, 8)}</dd></div>
        <div><dt>OPERACIÓN</dt><dd>{context.tipo_uso === 'APORTE' ? 'Aportar insumos' : 'Crear bolsa preparada'}</dd></div>
        <div><dt>RECETA</dt><dd>{context.receta_nombre || 'Receta de la OPM'}</dd></div>
        <div><dt>OBJETIVO</dt><dd>{context.objetivo_kg ? `${Number(context.objetivo_kg).toFixed(3)} kg` : 'Según OPM'}</dd></div>
      </dl>}
      {context?.tipo_uso === 'APORTE' && <>
        <label htmlFor="source-unit-qr">Escanear bolsa de materia prima (una por vez)</label>
        <input id="source-unit-qr" value={sourceQr} onChange={(event) => setSourceQr(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); acceptSourceQr(); } }} placeholder="SCM:UL:… y Enter" />
        {sourceUnits.length > 0 && <div className="scm-message success">
          <strong>{sourceUnits.length} bolsa(s) verificadas · {sourceUnits.reduce((sum, item) => sum + Number(item.cantidad_utilizable_kg || 0), 0).toFixed(3)} kg utilizables</strong>
          {sourceUnits.map((item, index) => {
            const requiredNet = Math.max(0, Number(peso || 0) - Number(tare || 0));
            const priorAvailable = sourceUnits.slice(0, index).reduce((sum, prior) => sum + Number(prior.cantidad_utilizable_kg || 0), 0);
            const usable = Number(item.cantidad_utilizable_kg || 0);
            const estimatedTake = Math.min(usable, Math.max(0, requiredNet - priorAvailable));
            return <div key={item.id}>{index + 1}. {item.codigo} · {item.material.codigo} · disponible {usable.toFixed(3)} kg · uso estimado {estimatedTake.toFixed(3)} kg · remanente {(usable - estimatedTake).toFixed(3)} kg</div>;
          })}
          <div>NET actual a cubrir: {Math.max(0, Number(peso || 0) - Number(tare || 0)).toFixed(3)} kg · faltante estimado: {Math.max(0, Number(peso || 0) - Number(tare || 0) - sourceUnits.reduce((sum, item) => sum + Number(item.cantidad_utilizable_kg || 0), 0)).toFixed(3)} kg</div>
        </div>}
      </>}
      <label htmlFor="prepared-tare">Tara (kg)</label><input id="prepared-tare" type="number" min="0" step="0.001" value={tare} onChange={(event) => setTare(event.target.value)} />
      <div className="scm-message info" role="status">{message}</div>
      <button className="btn btn-primary" disabled={!context || busy || (context.tipo_uso === 'APORTE' && sourceQrs.length === 0)} onClick={capture}>Confirmar pesaje (F2)</button>
    </div></section>
    <section className="panel"><div className="panel-header">LECTURA DE BALANZA</div><div className="panel-body">
      <div className="weight-display"><span>PESO BRUTO ACTUAL</span><strong>{Number(peso || 0).toFixed(3)} kg</strong><small>{listening ? 'Lectura en vivo' : 'Balanza desconectada'}</small></div>
      {simulationEnabled && <div className="simulation-panel"><strong>Modo local · balanza simulada</strong><div><input value={simulated} onChange={(event) => setSimulated(event.target.value)} /><button className="btn" onClick={() => onSimulateWeight(simulated)}>Aplicar peso simulado</button></div></div>}
      {result && <div className="scm-message success"><strong>Lectura {result.id}</strong><div>{result.tipo_uso} · NET {result.peso_neto_kg} kg</div><div>Estado: {result.estado}</div></div>}
    </div></section>
  </div>;
}
