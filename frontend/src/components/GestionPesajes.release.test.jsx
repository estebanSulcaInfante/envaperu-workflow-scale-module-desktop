import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import GestionPesajes from './GestionPesajes'


const apiMocks = vi.hoisted(() => ({
  buscar: vi.fn(),
  imprimir: vi.fn(),
  solicitarCorreccion: vi.fn(),
}))

vi.mock('../services/api', () => ({
  pesajesApi: apiMocks,
}))

const pesaje = {
  id: 7,
  fecha_hora: '2026-07-17T10:00:00',
  peso_kg: 30.125,
  nro_op: 'OP-1401',
  molde: 'BOTELLA 1L',
  maquina: 'SOPLADORA-01',
  nro_orden_trabajo: 'OT-30041',
  color: 'ROJO',
  operador: 'OPERADOR ORIGINAL',
  traceability_classification: 'LOCAL_CAPTURE',
  latest_correction_request: null,
}


describe('GestionPesajes release guardrails', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.buscar.mockResolvedValue({
      data: { items: [pesaje], page: 1, pages: 1, total: 1 },
    })
    apiMocks.solicitarCorreccion.mockResolvedValue({
      data: {
        correction_request: { id: 91, status: 'PENDING_LOCAL_REVIEW' },
      },
    })
  })

  it('removes delete and bulk-selection controls from the operator surface', async () => {
    render(<GestionPesajes uuidFactory={() => 'request-guardrail-1'} />)

    await screen.findByText('OP-1401')

    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByTitle('Eliminar')).toBeNull()
    expect(screen.queryByText(/eliminar pesajes/i)).toBeNull()
    expect(
      screen.getByRole('button', {
        name: 'Solicitar corrección del pesaje #7',
      }),
    ).toBeTruthy()
  })

  it('records an idempotent correction request instead of editing the row', async () => {
    render(<GestionPesajes uuidFactory={() => 'request-guardrail-2'} />)
    await screen.findByText('OP-1401')

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Solicitar corrección del pesaje #7',
      }),
    )

    expect(
      screen.getByRole('heading', { name: 'Solicitar corrección' }),
    ).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Peso propuesto (kg)'), {
      target: { value: '30.250' },
    })
    fireEvent.change(screen.getByLabelText('Solicitado por'), {
      target: { value: 'SUPERVISOR TURNO A' },
    })
    fireEvent.change(screen.getByLabelText('Motivo'), {
      target: { value: 'La bolsa fue asociada al registro equivocado.' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Registrar solicitud' }),
    )

    await waitFor(() => {
      expect(apiMocks.solicitarCorreccion).toHaveBeenCalledTimes(1)
    })
    expect(apiMocks.solicitarCorreccion).toHaveBeenCalledWith(
      7,
      expect.objectContaining({
        action: 'CORRECT',
        requested_by: 'SUPERVISOR TURNO A',
        reason: 'La bolsa fue asociada al registro equivocado.',
        proposed_changes: expect.objectContaining({ peso_kg: '30.250' }),
      }),
      'request-guardrail-2',
    )
    expect(apiMocks.buscar).toHaveBeenCalledTimes(2)
  })
})
