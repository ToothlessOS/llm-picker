import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { HomePage } from './HomePage'

describe('HomePage', () => {
  it('renders the cover, four chart stages, and data links', () => {
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    )

    expect(
      screen.getByRole('heading', { name: /Which model is worth/ }),
    ).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Performance vs. cost' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Cost per task' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Task fit' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Model card' })).toBeTruthy()
    expect(screen.getByRole('link', { name: /Complete matched table/ }).getAttribute('href')).toBe(
      '/models',
    )
    expect(screen.getByRole('link', { name: /Task leaderboards/ }).getAttribute('href')).toBe(
      '/categories',
    )
    expect(screen.getByRole('link', { name: /Full AA catalog/ }).getAttribute('href')).toBe(
      '/artificial-analysis',
    )
    expect(screen.getByRole('link', { name: /Matching and freshness/ }).getAttribute('href')).toBe(
      '/data-quality',
    )

    const dataHeading = screen.getByRole('heading', { name: 'Models' })
    const cover = screen.getByRole('heading', { name: /Which model is worth/ })
    expect(
      Boolean(dataHeading.compareDocumentPosition(cover) & Node.DOCUMENT_POSITION_FOLLOWING),
    ).toBe(true)
  })
})
