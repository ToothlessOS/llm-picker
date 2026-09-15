import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, ApiNetworkError, type MetadataResponse } from '../../api'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { FreshnessBanner } from './FreshnessBanner'

describe('request states', () => {
  it('shows a retry action for network errors', () => {
    const retry = vi.fn()
    render(
      <ErrorState
        error={new ApiNetworkError('/api/overview/', new Error('offline'))}
        onRetry={retry}
      />,
    )

    expect(screen.getByRole('alert').textContent).toContain('Backend unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it('uses the backend throttling message', () => {
    render(
      <ErrorState
        error={new ApiError(
          429,
          {
            error: 'throttled',
            message: 'Try again in one minute.',
          },
          '/api/overview/',
        )}
      />,
    )

    expect(screen.getByRole('alert').textContent).toContain('Too many requests')
    expect(screen.getByRole('alert').textContent).toContain(
      'Try again in one minute.',
    )
  })

  it('renders an empty state message', () => {
    render(<EmptyState message="No models match these filters." />)
    expect(screen.getByText('No models match these filters.')).toBeTruthy()
  })
})

describe('FreshnessBanner', () => {
  it('only reports sources that need attention', () => {
    const source = {
      configured: true,
      last_attempt_at: '2026-09-13T00:00:00Z',
      last_status: 'success' as const,
      last_success_at: '2026-09-13T00:00:00Z',
      age_seconds: 60,
      is_stale: false,
      stale_after_seconds: 50_400,
      last_error: null,
    }
    const metadata = {
      sources: {
        lmarena: source,
        artificial_analysis: { ...source, is_stale: true },
      },
    } as MetadataResponse

    render(<FreshnessBanner metadata={metadata} />)

    expect(screen.getByRole('status').textContent).toContain(
      'Artificial Analysis',
    )
    expect(screen.getByRole('status').textContent).not.toContain('LMArena')
  })
})
