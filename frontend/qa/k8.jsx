// Isolated visual fixture. Not part of the production entrypoint or build.
import React, { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import ScmWeighing from '../src/components/ScmWeighing';
import { scmWeighingApi } from '../src/services/api';
import '../src/index.css';

if (!import.meta.env.DEV || !['127.0.0.1', 'localhost'].includes(location.hostname)) {
  throw new Error('QA K8 solo disponible en desarrollo local.');
}

const targetState = new URLSearchParams(location.search).get('state') || 'ready';
const context = {
  can_weigh: true,
  can_register_weight_control: true,
  scanned_label_id: 'ba676a92-97ba-40d6-a8a3-6331e1e83a7f',
  bloqueos_pesaje: { completar_final: null, registrar_avance_kg: null },
  continuidad: {
    ultima_referencia_peso: {
      fuente: 'CONTROL_PESO',
      peso_neto_kg: '4.790',
      tara_kg: '0.030',
    },
  },
  manga: {
    codigo: 'OF000001-OT002-M001',
    public_id: 'cc2319c4-a157-4b6e-925a-0fe2489efeaf',
    tipo: 'NORMAL',
    estado: 'EN_LLENADO',
    tara_nominal_kg: '0.030',
    peso_bruto_max_kg: '15.000',
    peso_fabricado_teorico_kg: '6.700',
    pieza_color: 'JARRA REAL 6 LT TRANSPARENTE',
    color: 'TRANSPARENTE',
    color_identidad: { nombre: 'TRANSPARENTE', familia: { nombre: 'TRANSPARENTE' } },
    fecha_operativa: '2026-09-02',
    maquinista: 'Jose Quispe',
    ot: { codigo: 'OT-000002', maquina: 'INY-01', turno: 'DIA' },
    trabajo_color: {
      codigo: 'OT-000002-TC01',
      estado: 'EN_EJECUCION',
      orden_fabricacion: 'OF-000001',
      corrida: 'OF-000001-C01',
      color: 'TRANSPARENTE',
    },
  },
};

scmWeighingApi.resolve = async () => ({ data: context });
scmWeighingApi.control = async () => ({
  data: {
    control: {
      tipo: 'AVANCE_KG',
      peso_neto_kg: '5.070',
      aporte_desde_control_anterior_kg: '0.280',
      conteo_acumulado_un: null,
    },
    manga: { estado: 'EN_LLENADO' },
    print_result: { result: 'SIMULADA' },
  },
});

function setInputValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    'value',
  ).set;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

function Fixture() {
  useEffect(() => {
    const scanTimer = window.setTimeout(() => {
      const scanner = document.querySelector('[aria-label="QR de manga SCM"]');
      if (!scanner) return;
      setInputValue(scanner, 'qa-k8');
      window.setTimeout(() => {
        scanner.dispatchEvent(new KeyboardEvent('keydown', {
          key: 'Enter', bubbles: true,
        }));
      }, 60);
    }, 120);
    const controlTimer = targetState === 'consumed'
      ? window.setTimeout(() => {
          document.querySelector('.scm-f2-button:not([disabled])')?.click();
        }, 800)
      : null;
    return () => {
      window.clearTimeout(scanTimer);
      if (controlTimer) window.clearTimeout(controlTimer);
    };
  }, []);

  return (
    <main style={{ padding: 16, maxWidth: 1600, margin: 'auto' }}>
      <div style={{ marginBottom: 12 }}>
        <strong>QA local K8 · datos ficticios · sin mutación Central</strong>
      </div>
      <ScmWeighing
        peso={5.1}
        listening
        centralState="ONLINE"
        onConnect={() => {}}
      />
    </main>
  );
}

createRoot(document.getElementById('root')).render(<Fixture />);
