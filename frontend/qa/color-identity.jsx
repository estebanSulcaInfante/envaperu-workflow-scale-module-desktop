// Isolated visual fixture. Not part of the production entrypoint or build.
import React, { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import ScmWeighing from '../src/components/ScmWeighing';
import { scmWeighingApi } from '../src/services/api';
import '../src/index.css';

if (!import.meta.env.DEV || !['127.0.0.1', 'localhost'].includes(location.hostname)) {
  throw new Error('QA de identidad de color solo disponible en desarrollo local.');
}

scmWeighingApi.resolve = async () => ({
  data: {
    can_weigh: false,
    can_register_weight_control: false,
    scanned_label_id: 'qa-color-identity-local',
    bloqueos_pesaje: {
      completar_final: {
        codigo: 'TRABAJO_NO_INICIADO',
        mensaje: 'Trabajo de la OT sin iniciar',
        recuperacion: 'Solicite a Central iniciar el Trabajo de la OT y vuelva a escanear.',
        responsable: 'CENTRAL',
      },
      registrar_avance_kg: {
        codigo: 'TRABAJO_NO_INICIADO',
        mensaje: 'Trabajo de la OT sin iniciar',
        recuperacion: 'Solicite a Central iniciar el Trabajo de la OT y vuelva a escanear.',
        responsable: 'CENTRAL',
      },
    },
    manga: {
      codigo: 'OF000001-OT002-M001',
      estado: 'PREETIQUETADA',
      tipo: 'NORMAL',
      cantidad_asignada_un: '120',
      tara_nominal_kg: '0.020',
      pieza_color: 'Jarra Real 6 L Transparente (PC-000777)',
      articulo_clase: 'PIEZA_COLOR',
      articulo_codigo: 'PC-000777',
      color: 'TRANSPARENTE',
      color_hex: '#EAF7F7',
      color_identidad: {
        id: 7,
        nombre: 'TRANSPARENTE',
        base: { id: 4, nombre: 'TRANSPARENTE' },
        familia: { id: 3, nombre: 'TRANSPARENTE' },
        hex: '#EAF7F7',
      },
      imagen_url: null,
      fecha_operativa: '2026-09-02',
      maquinista: 'Jose Quispe',
      ot: { codigo: 'OT-000002', maquina: 'INY-01', turno: 'DIA' },
      trabajo_color: {
        codigo: 'OT-000002-TC01',
        estado: 'PLANIFICADO',
        orden_fabricacion: 'OF-000001',
        corrida: 'OF-000001-C01',
        color: 'TRANSPARENTE',
      },
    },
  },
});

function Fixture() {
  useEffect(() => {
    const timer = window.setTimeout(() => {
      document.querySelector('.portfolio-weighing-guide button')?.click();
    }, 100);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <main style={{ maxWidth: 1500, margin: '0 auto', padding: 16 }}>
      <div className="scm-message info">
        QA local · identidad de color · datos ficticios · sin red, pesaje ni impresión
      </div>
      <ScmWeighing
        peso={7.6}
        listening
        centralState="ONLINE"
        onConnect={() => {}}
        simulationEnabled
        portfolioDemoMode
      />
    </main>
  );
}

createRoot(document.getElementById('root')).render(<Fixture />);
