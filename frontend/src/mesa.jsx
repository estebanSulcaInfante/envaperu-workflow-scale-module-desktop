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
        <a href="/" aria-current={pathname === '/' ? 'page' : undefined}>Retornos de Armado</a>
        <a href="/inventario/mesa" aria-current={view === 'mesa' ? 'page' : undefined}>Inventario de mesa</a>
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
