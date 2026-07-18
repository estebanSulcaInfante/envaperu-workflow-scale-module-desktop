import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import CentralStatusBadge from './CentralStatusBadge';


describe('CentralStatusBadge', () => {
  it('distingue central online de la balanza local', () => {
    render(<CentralStatusBadge state="ONLINE" />);

    const badge = screen.getByRole('status', { name: 'Central en línea' });
    expect(badge.className).toContain('central-online');
  });

  it('muestra una caída central como degradación informativa', () => {
    render(<CentralStatusBadge state="CENTRAL_UNREACHABLE" />);

    const badge = screen.getByRole('status', { name: 'Central sin conexión' });
    expect(badge.className).toContain('central-degraded');
    expect(screen.queryByRole('button')).toBeNull();
  });
});
