import React from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import MesaReturnsPilot from './components/MesaReturnsPilot';
import MesaInventory from './components/MesaInventory';

function inventoryView(pathname) {
  if (pathname === '/inventario/mesa') return 'mesa';
  if (pathname === '/inventario/revision') return 'revision';
  if (pathname === '/inventario/c66') return 'c66';
  return null;
}

function MesaPilot() {
  const pathname = globalThis.location?.pathname || '';
  const view = inventoryView(pathname);
  const lanMode = !['localhost', '127.0.0.1', '::1', ''].includes(globalThis.location?.hostname || '');
  return (
    <div className="mesa-pilot-route-shell">
      {!lanMode && <nav className="mesa-pilot-route-nav" aria-label="Rutas de la estación">
        <a href="/">Retornos de Armado</a>
        <a href="/inventario/c66">Inventario C66</a>
        <a href="/inventario/mesa">Inventario mesa</a>
        <a href="/inventario/revision">Revisión</a>
        <a href="/inventario/conectar">Conectar C66</a>
      </nav>}
      {view ? <MesaInventory initialView={view} /> : <MesaReturnsPilot showExamples />}
    </div>
  );
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <MesaPilot />
  </React.StrictMode>,
);
