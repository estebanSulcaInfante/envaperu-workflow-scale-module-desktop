import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import CaptureResultNotice from './CaptureResultNotice'


describe('CaptureResultNotice', () => {
  it('keeps the saved result visible and retries only printing', () => {
    const onRetryPrint = vi.fn()
    render(
      <CaptureResultNotice
        result={{
          status: 'SAVED_PRINT_FAILED',
          pesaje: { id: 41, capture_id: 'capture-41', peso_kg: 30 },
        }}
        onRetryPrint={onRetryPrint}
      />,
    )

    expect(
      screen.getByText('Pesaje guardado; impresi\u00f3n fallida'),
    ).toBeTruthy()
    expect(screen.getByText(/#41/)).toBeTruthy()
    expect(screen.getByText(/30\.000 kg/)).toBeTruthy()

    fireEvent.click(
      screen.getByRole('button', { name: 'Reintentar impresi\u00f3n' }),
    )

    expect(onRetryPrint).toHaveBeenCalledWith('capture-41')
  })
})
