import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { HomePage } from './HomePage'

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    // The discussion-map card reads the counts `AppShell` already polls — same
    // cache key, so it costs no extra request. Mocked because a real one would
    // be a network call from jsdom.
    getMetadata: vi.fn().mockResolvedValue({
      discussions: {
        counts: { threads: 113, comments: 21_103, tags: 4_543, entities: 52 },
      },
    }),
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
  it('renders the cover, the chart stages, the discussion map, and data links', () => {
    renderHome()

    expect(
      screen.getByRole('heading', { name: /Find the right model/ }),
    ).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Performance explorer' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Cost Breakdown' })).toBeTruthy()
    expect(screen.getByText('Where does the money go?')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Task Fit' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Model Card' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Explore further' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Performance explorer' }).getAttribute('href')).toBe(
      '/visualizations/performance-vs-cost',
    )
    expect(screen.getByRole('link', { name: 'Cost Breakdown' }).getAttribute('href')).toBe(
      '/visualizations/cost-per-task',
    )
    expect(screen.getByRole('link', { name: 'Task Fit' }).getAttribute('href')).toBe(
      '/visualizations/task-fit',
    )
    expect(screen.getByRole('link', { name: 'Model Card' }).getAttribute('href')).toBe(
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

    expect(screen.getByRole('link', { name: 'What are people saying?' }).getAttribute('href')).toBe(
      '/discussions/map',
    )
    // The placeholder this feature replaced. Named as a test so that putting it
    // back — or shipping the card without a working link — fails loudly.
    expect(screen.queryByText(/coming soon/i)).toBeNull()

    const dataHeading = screen.getByRole('heading', { name: 'Models' })
    const cover = screen.getByRole('heading', { name: /Find the right model/ })
    expect(
      Boolean(dataHeading.compareDocumentPosition(cover) & Node.DOCUMENT_POSITION_FOLLOWING),
    ).toBe(true)
  })
})
