// @vitest-environment jsdom
import { act, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

vi.mock('./components/MesaReturnsPilot', () => ({ default: () => null }));
vi.mock('./components/MesaInventory', () => ({ default: () => null }));

it('muestra los dos destinos del puesto y señala Inventario de mesa al abrirlo', async () => {
  window.history.replaceState(null, '', '/inventario/mesa');
  document.body.innerHTML = '<div id="root"></div>';
  await act(async () => { await import('./mesa'); });
  const nav = await within(document.body).findByRole('navigation', { name: 'Rutas de la estación' });
  const links = within(nav).getAllByRole('link');
  expect(links.map(link => [link.textContent, link.getAttribute('href')])).toEqual([
    ['Retornos de Armado', '/'],
    ['Inventario de mesa', '/inventario/mesa'],
  ]);
  expect(links[1].getAttribute('aria-current')).toBe('page');
});
