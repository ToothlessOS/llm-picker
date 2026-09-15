import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { OverviewRow } from '../../api'
import { ModelCardPage } from './ModelCardPage'

const makeRow = vi.hoisted(() => {
  return function makeRow(input: {
    key: string
    name: string
    organization: string
    intelligence: number | null
    coding: number | null
    agentic: number | null
    cost: number | null
    speed: number | null
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
        intelligence_index_version: 4.3,
        intelligence_index: input.intelligence,
        coding_index: input.coding,
        agentic_index: input.agentic,
        intelligence_index_total_cost: null,
        cost_per_task: input.cost,
        pricing: {
          price_1m_input_tokens: 1,
          price_1m_output_tokens: 3,
          price_1m_cache_hit_tokens: null,
          price_1m_cache_write_tokens: null,
        },
        performance: {
          median_output_tokens_per_second: input.speed,
          median_time_to_first_token_seconds: 1,
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
      count: 2,
      next: null,
      previous: null,
      page_size: 200,
      results: [
        makeRow({
          key: 'alpha',
          name: 'Alpha model',
          organization: 'openai',
          intelligence: 50,
          coding: 80,
          agentic: 40,
          cost: 2,
          speed: 60,
        }),
        makeRow({
          key: 'gamma',
          name: 'Gamma model',
          organization: 'anthropic',
          intelligence: 20,
          coding: null,
          agentic: 10,
          cost: 0.4,
          speed: 120,
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
        <ModelCardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ModelCardPage', () => {
  it('profiles the default model and keeps a missing coding index as not measured', async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Model card' })).toBeTruthy()
    expect(await screen.findByRole('heading', { name: 'Alpha model' })).toBeTruthy()
    expect(screen.getByRole('link', { name: /Open model page/ }).getAttribute('href')).toBe(
      '/models/alpha',
    )

    await user.click(screen.getByRole('button', { name: /Gamma model/ }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Gamma model' })).toBeTruthy()
    })
    expect(screen.getByRole('link', { name: /Open model page/ }).getAttribute('href')).toBe(
      '/models/gamma',
    )
    expect(screen.getByText(/shown as a gap, not zero/)).toBeTruthy()
  })
})
