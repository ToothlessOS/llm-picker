import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { OverviewRow } from '../../api'
import { PerformanceVsCostPage } from './PerformanceVsCostPage'

const makeRow = vi.hoisted(() => {
  return function makeRow(input: {
    key: string
    name: string
    organization: string
    intelligence: number | null
    cost: number | null
  }): OverviewRow {
    return {
      model: {
        key: input.key,
        name: input.name,
        organization: input.organization,
        license: null,
        in_agent_set: true,
      },
      categories: {
        agent: {
          category: 'agent',
          metric_kind: 'score',
          metric_value: 0.1,
          metric_lower: null,
          metric_upper: null,
          metric_variance: null,
          sample_size: 10,
          session_count: 10,
          rank: 1,
          model_name: input.name,
          organization: input.organization,
          license: null,
          leaderboard_publish_date: '2026-09-01',
          source_key: input.key,
          matched_by_fold: false,
        },
        document: null,
        search: null,
        webdev: null,
      },
      aa: {
        id: input.key,
        slug: input.key,
        name: input.name,
        creator: { id: input.organization, name: input.organization },
        release_date: null,
        intelligence_index_version: 1,
        intelligence_index: input.intelligence,
        coding_index: null,
        agentic_index: null,
        intelligence_index_total_cost: null,
        cost_per_task: input.cost,
        pricing: {
          price_1m_input_tokens: null,
          price_1m_output_tokens: null,
          price_1m_cache_hit_tokens: null,
          price_1m_cache_write_tokens: null,
        },
        performance: {
          median_output_tokens_per_second: null,
          median_time_to_first_token_seconds: null,
          median_time_to_first_answer_token_seconds: null,
          median_end_to_end_response_time_seconds: null,
        },
        is_retained: true,
        last_synced_at: '2026-09-15T00:00:00Z',
      },
      match: {
        method: 'exact_key',
        confidence: 1,
        is_manual: false,
        matched_key: input.key,
        last_matched_at: '2026-09-15T00:00:00Z',
      },
    }
  }
})

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    getOverview: vi.fn().mockResolvedValue({
      count: 3,
      next: null,
      previous: null,
      page_size: 200,
      results: [
        makeRow({
          key: 'cheap-weak',
          name: 'Cheap weak',
          organization: 'xiaomi',
          intelligence: 20,
          cost: 0.1,
        }),
        makeRow({
          key: 'mid',
          name: 'Balanced',
          organization: 'openai',
          intelligence: 40,
          cost: 0.5,
        }),
        makeRow({
          key: 'expensive-weak',
          name: 'Expensive weak',
          organization: 'google',
          intelligence: 25,
          cost: 2,
        }),
      ],
      meta: {
        generated_at: '2026-09-15T00:00:00Z',
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
      <MemoryRouter>
        <PerformanceVsCostPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PerformanceVsCostPage', () => {
  it('lists Pareto models and inspects one on hover', async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Performance vs. cost' })).toBeTruthy()
    const cheap = await screen.findByRole('link', { name: /Cheap weak/ })
    expect(cheap.getAttribute('href')).toBe('/models/cheap-weak')
    expect(screen.getByRole('link', { name: /Balanced/ })).toBeTruthy()
    expect(screen.queryByRole('link', { name: /Expensive weak/ })).toBeNull()

    await user.hover(cheap)
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Cheap weak' })).toBeTruthy()
    })
    expect(screen.getByText(/On the Pareto front/)).toBeTruthy()
  })
})
