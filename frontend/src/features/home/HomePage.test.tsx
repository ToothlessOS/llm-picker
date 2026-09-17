import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { HomePage } from './HomePage'

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    getOverview: vi.fn().mockResolvedValue({
      count: 0,
      next: null,
      previous: null,
      page_size: 200,
      results: [],
      meta: {
        generated_at: '2026-09-15T00:00:00Z',
        sources: {},
        categories_included: [],
      },
    }),
  }
})

function renderHome() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('HomePage', () => {
  it('renders the cover, four chart stages, and data links', () => {
    renderHome()

    expect(
      screen.getByRole('heading', { name: /Which model is worth/ }),
    ).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Performance vs. cost' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Cost per task' })).toBeTruthy()
    expect(screen.getByText('Where does the money go? Split by list prices, not usage.')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Task fit' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Model card' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Performance vs. cost' }).getAttribute('href')).toBe(
      '/visualizations/performance-vs-cost',
    )
    expect(screen.getByRole('link', { name: 'Cost per task' }).getAttribute('href')).toBe(
      '/visualizations/cost-per-task',
    )
    expect(screen.getByRole('link', { name: 'Task fit' }).getAttribute('href')).toBe(
      '/visualizations/task-fit',
    )
    expect(screen.getByRole('link', { name: 'Model card' }).getAttribute('href')).toBe(
      '/visualizations/model-card',
    )
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
