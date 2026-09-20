import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { InterimCheckInPage } from './InterimCheckInPage'

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  const freshness = {
    configured: true,
    last_attempt_at: '2026-09-20T02:00:00Z',
    last_status: 'success',
    last_success_at: '2026-09-20T02:00:00Z',
    age_seconds: 60,
    is_stale: false,
    stale_after_seconds: 86_400,
    last_error: null,
  }

  return {
    ...actual,
    getMetadata: vi.fn().mockResolvedValue({
      sources: {
        lmarena: freshness,
        artificial_analysis: freshness,
      },
      counts: {
        lmarena_entries: 243,
        lmarena_agent_entries: 43,
        complete_agent_entries: 30,
        aa_models: 647,
        aa_models_retained: 647,
        matches: 30,
        unmatched_records: 907,
      },
      categories: [],
      matching: { exact_name: 26, exact_slug: 4 },
      recent_runs: [],
      config: { harness_fold_enabled: true, stale_after_seconds: 86_400 },
      attribution: { artificial_analysis: 'Artificial Analysis', lmarena: 'LMArena' },
      meta: {
        generated_at: '2026-09-20T02:01:00Z',
        sources: {
          lmarena: freshness,
          artificial_analysis: freshness,
        },
      },
    }),
    getOverview: vi.fn().mockResolvedValue({
      count: 0,
      next: null,
      previous: null,
      page_size: 200,
      results: [],
      meta: {
        generated_at: '2026-09-20T02:01:00Z',
        sources: {},
        categories_included: [],
      },
    }),
  }
})

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/interim-check-in']}>
        <InterimCheckInPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('InterimCheckInPage', () => {
  it('presents the four checkpoint sections and live dataset counts', async () => {
    renderPage()

    expect(screen.getByRole('heading', { name: 'Dataset' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Visualizations' })).toBeTruthy()
    expect(
      screen.getByRole('heading', { name: 'Interaction / Animation Plan' }),
    ).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Evaluation Plan' })).toBeTruthy()

    expect(await screen.findByText('243')).toBeTruthy()
    expect(screen.getByText('647')).toBeTruthy()
    expect(screen.getByText('43')).toBeTruthy()
    expect(screen.getByText('30')).toBeTruthy()
  })

  it('links every preview to its full visualization', () => {
    renderPage()

    expect(
      screen.getByRole('link', { name: 'Performance vs. cost' }).getAttribute('href'),
    ).toBe('/visualizations/performance-vs-cost')
    expect(
      screen.getByRole('link', { name: 'Cost per task' }).getAttribute('href'),
    ).toBe('/visualizations/cost-per-task')
    expect(
      screen.getByRole('link', { name: 'Task fit' }).getAttribute('href'),
    ).toBe('/visualizations/task-fit')
    expect(
      screen.getByRole('link', { name: 'Model card' }).getAttribute('href'),
    ).toBe('/visualizations/model-card')
  })
})
