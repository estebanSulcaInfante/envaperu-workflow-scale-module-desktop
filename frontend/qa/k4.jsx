// Isolated visual fixture. Not part of the production entrypoint or build.
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import ScmWeighing from '../src/components/ScmWeighing';
import { scmWeighingApi } from '../src/services/api';
import '../src/index.css';

if (!import.meta.env.DEV || !['127.0.0.1', 'localhost'].includes(location.hostname)) {
  throw new Error('QA K4 solo disponible en desarrollo local.');
}
let scenario = 'cerrada';
let currentWeight = 7.6;
let control = null;
const reasons = {
  cerrada: ['MANGA_CERRADA', 'Manga cerrada', 'Escanee otra manga. Si el cierre fue incorrecto, solicite revisión en Central.'],
  planificada: ['TRABAJO_NO_INICIADO', 'Trabajo de la OT sin iniciar', 'Solicite a Central iniciar el Trabajo de la OT y vuelva a escanear.'],
  continuidad: ['CONTINUIDAD_PENDIENTE', 'Continuidad pendiente de vinculación', 'Solicite a Central revisar el vínculo al Trabajo que continuará la manga. Conserve el mismo QR.'],
};
scmWeighingApi.resolve = async (qr) => {
  if (qr === 'invalido') throw { response: { data: { message: 'Etiqueta invalidada. Utilice la preetiqueta vigente.' } } };
  const reason = reasons[scenario];
  const blocker = reason && { codigo: reason[0], mensaje: reason[1], recuperacion: reason[2], responsable: 'CENTRAL' };
  return { data: { can_weigh: !reason, can_register_weight_control: !reason,
    scanned_label_id: 'qa-k4-local',
    bloqueos_pesaje: { completar_final: blocker || null, registrar_avance_kg: blocker || null },
    continuidad: { ultimo_control: control },
    manga: { codigo: 'OF000017-OT007-M006', tipo: 'NORMAL',
      estado: scenario === 'cerrada' ? 'PESADA' : scenario === 'continuidad' ? 'CONTINUIDAD_PENDIENTE' : control ? 'EN_LLENADO' : 'PREETIQUETADA',
      cantidad_asignada_un: '60', tara_nominal_kg: '0.020', peso_bruto_max_kg: '15',
      pieza_color: 'EMBUDO #4', color: 'ANARANJADO SÓLIDO', imagen_url: null,
      fecha_operativa: '2026-09-02', maquinista: 'Operador de prueba',
      ot: { codigo: 'OT-000007', maquina: 'HT-360 A', turno: 'DIA' },
      trabajo_color: { codigo: 'TC01', estado: scenario === 'planificada' ? 'PLANIFICADO' : 'EN_EJECUCION',
        orden_fabricacion: 'OF000017', corrida: 'C01', color: 'ANARANJADO SÓLIDO' },
    },
  } };
};
scmWeighingApi.control = async () => {
  const net = Number((currentWeight - 0.020).toFixed(3));
  const previous = Number(control?.peso_neto_kg || 0);
  control = { tipo: 'AVANCE_KG', peso_neto_kg: net.toFixed(3),
    aporte_desde_control_anterior_kg: (net - previous).toFixed(3), conteo_acumulado_un: null };
  return { data: { control, manga: { estado: 'EN_LLENADO' }, print_result: { result: 'SIMULADA' } } };
};
scmWeighingApi.confirm = async () => ({ data: {
  confirmed: { weighing: { estado_manga: 'PESADA', peso_fisico_neto_kg: (currentWeight - 0.020).toFixed(3),
    kg_produccion_ot: '7.560', cantidad_confirmada: '60', fuente_cantidad: 'PLAN_CONFIRMADO_POR_PESAJE' } },
  print_result: { result: 'SIMULADA' },
} });

function Fixture() {
  const [selected, setSelected] = useState(scenario);
  const [weight, setWeight] = useState(currentWeight);
  return <main style={{ padding: 16, maxWidth: 1600, margin: 'auto' }}>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', marginBottom: 16 }}>
      <strong>QA local K4 · datos ficticios · sin red ni impresión</strong>
      <label>Escenario QA <select aria-label="Escenario QA" value={selected} onChange={(event) => {
        scenario = event.target.value; control = null; setSelected(scenario);
      }}>
        <option value="cerrada">Manga cerrada</option><option value="planificada">Trabajo sin iniciar</option>
        <option value="continuidad">Continuidad pendiente</option><option value="abierta">Manga abierta</option>
        <option value="offline">Central desconectada</option><option value="balanza">Balanza desconectada</option>
      </select></label>
      <label>Peso QA <input aria-label="Peso QA" type="number" step="0.001" value={weight} onChange={(event) => {
        currentWeight = Number(event.target.value); setWeight(currentWeight);
      }} style={{ width: 90 }} /></label>
      <small>Escriba «qa» en el lector y Enter; «invalido» prueba rechazo.</small>
    </div>
    <ScmWeighing key={selected} peso={weight} listening={selected !== 'balanza'}
      centralState={selected === 'offline' ? 'OFFLINE' : 'ONLINE'} onConnect={() => {}} />
  </main>;
}
createRoot(document.getElementById('root')).render(<Fixture />);
