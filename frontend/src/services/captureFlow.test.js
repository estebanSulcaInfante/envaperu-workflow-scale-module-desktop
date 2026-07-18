import { describe, expect, it, vi } from 'vitest'

import {
  createCaptureCoordinator,
  submitCaptureAndPrint,
} from './captureFlow'


describe('capture coordinator', () => {
  it('keeps the same capture id and frozen payload until capture is conclusive', () => {
    const ids = ['capture-1', 'capture-2']
    const coordinator = createCaptureCoordinator({
      uuid: () => ids.shift(),
    })
    const payload = { peso_kg: 30.125, nro_op: 'OP-1401' }

    const firstF2 = coordinator.begin(payload)
    payload.peso_kg = 99
    const secondF2 = coordinator.begin({ peso_kg: 40, nro_op: 'OP-OTHER' })

    expect(secondF2.captureId).toBe(firstF2.captureId)
    expect(secondF2.payload).toEqual({ peso_kg: 30.125, nro_op: 'OP-1401' })

    coordinator.complete(firstF2.captureId)
    expect(coordinator.begin(payload).captureId).toBe('capture-2')
  })

  it('does not create another capture when printing fails', async () => {
    const captureRequest = vi.fn().mockResolvedValue({
      status: 201,
      data: {
        status: 'SAVED_PRINT_PENDING',
        pesaje: { id: 7, capture_id: 'capture-7' },
      },
    })
    const printRequest = vi.fn().mockResolvedValue({
      data: {
        status: 'SAVED_PRINT_FAILED',
        print_attempt: { id: 12, result: 'FAILED' },
      },
    })

    const result = await submitCaptureAndPrint({
      session: {
        captureId: 'capture-7',
        payload: { peso_kg: 30.125, nro_op: 'OP-1401' },
      },
      captureRequest,
      printRequest,
    })

    expect(captureRequest).toHaveBeenCalledTimes(1)
    expect(printRequest).toHaveBeenCalledWith('capture-7')
    expect(result.captureSaved).toBe(true)
    expect(result.printStatus).toBe('SAVED_PRINT_FAILED')
    expect(result.pesaje.id).toBe(7)
    expect(result.attempt).toEqual({ id: 12, result: 'FAILED' })
  })
})
