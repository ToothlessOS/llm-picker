import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'

import { stopThemeClock } from '../app/theme'
import { ThemeToggle } from './ThemeToggle'

function SearchProbe() {
  const location = useLocation()
  return <output aria-label="location">{location.search || '(none)'}</output>
}

function renderToggle(search = '') {
  return render(
    <MemoryRouter initialEntries={[search ? `/${search}` : '/']}>
      <ThemeToggle />
      <SearchProbe />
    </MemoryRouter>,
  )
}

afterEach(() => {
  stopThemeClock()
})

describe('ThemeToggle', () => {
  it('shows day, night, and auto options at once', () => {
    renderToggle()

    const group = screen.getByRole('radiogroup', { name: 'Theme' })
    expect(group.getAttribute('data-theme-mode')).toBe('auto')
    expect(screen.getByRole('radio', { name: 'Day theme' })).toBeTruthy()
    expect(screen.getByRole('radio', { name: 'Night theme' })).toBeTruthy()
    expect(screen.getByRole('radio', { name: 'Auto theme' }).getAttribute('aria-checked')).toBe(
      'true',
    )
  })

  it('lets the user pick any mode directly', async () => {
    const user = userEvent.setup()
    renderToggle()

    await user.click(screen.getByRole('radio', { name: 'Night theme' }))
    expect(screen.getByLabelText('location').textContent).toBe('?theme=night')
    expect(screen.getByRole('radiogroup').getAttribute('data-theme-mode')).toBe('night')

    await user.click(screen.getByRole('radio', { name: 'Day theme' }))
    expect(screen.getByLabelText('location').textContent).toBe('?theme=day')
    expect(screen.getByRole('radiogroup').getAttribute('data-theme-mode')).toBe('day')

    await user.click(screen.getByRole('radio', { name: 'Auto theme' }))
    expect(screen.getByLabelText('location').textContent).toBe('(none)')
    expect(screen.getByRole('radiogroup').getAttribute('data-theme-mode')).toBe('auto')
  })
})
