import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { GlobalFilters } from './GlobalFilters'

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="location">{location.search}</output>
}

function renderFilters(initialEntry = '/') {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <GlobalFilters providerOptions={['Anthropic', 'OpenAI']} />
      <LocationProbe />
    </MemoryRouter>,
  )
}

describe('GlobalFilters', () => {
  it('reads filters from the URL and clears the page when a filter changes', () => {
    renderFilters('/?provider=Anthropic&page=4')

    expect((screen.getByLabelText('Provider') as HTMLSelectElement).value).toBe(
      'Anthropic',
    )
    fireEvent.change(screen.getByLabelText('Task'), {
      target: { value: 'search' },
    })

    const location = screen.getByLabelText('location').textContent ?? ''
    expect(location).toContain('provider=Anthropic')
    expect(location).toContain('category=search')
    expect(location).not.toContain('page=')
  })

  it('debounces model search into the URL', () => {
    vi.useFakeTimers()
    renderFilters()

    fireEvent.change(screen.getByLabelText('Find a model'), {
      target: { value: '  Claude  ' },
    })
    expect(screen.getByLabelText('location').textContent).toBe('')

    act(() => vi.advanceTimersByTime(300))
    expect(screen.getByLabelText('location').textContent).toBe('?q=Claude')
    vi.useRealTimers()
  })

  it('clears all active filters', () => {
    renderFilters('/?q=Gemini&provider=Google&category=agent')

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))

    expect(screen.getByLabelText('location').textContent).toBe('')
  })
})
