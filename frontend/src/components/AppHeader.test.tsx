import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { AppHeader } from './AppHeader'

describe('AppHeader', () => {
  it('shows the theme toggle on the home page', () => {
    render(
      <MemoryRouter>
        <AppHeader />
      </MemoryRouter>,
    )

    expect(screen.getByRole('radiogroup', { name: 'Theme' })).toBeTruthy()
    expect(screen.getByRole('radio', { name: 'Day theme' })).toBeTruthy()
    expect(screen.getByRole('radio', { name: 'Night theme' })).toBeTruthy()
    expect(screen.getByRole('radio', { name: 'Auto theme' })).toBeTruthy()
  })

  it('hides the theme toggle on data pages', () => {
    render(
      <MemoryRouter initialEntries={['/models']}>
        <AppHeader />
      </MemoryRouter>,
    )

    expect(screen.queryByRole('radiogroup', { name: 'Theme' })).toBeNull()
  })
})
