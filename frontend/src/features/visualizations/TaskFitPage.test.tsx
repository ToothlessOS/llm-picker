import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { CategoryBlock, OverviewRow } from '../../api'
import { TaskFitPage } from './TaskFitPage'

const makeBlock = vi.hoisted(() => {
  return function makeBlock(
    category: CategoryBlock['category'],
    input: {
      kind: CategoryBlock['metric_kind']
      name: string
      organization: string
      rank: number | null
      value: number | null
    },
  ): CategoryBlock {
    return {
      category,
      leaderboard_publish_date: '2026-09-01',
      license: null,
      matched_by_fold: false,
      metric_kind: input.kind,
      metric_lower: null,
      metric_upper: null,
      metric_value: input.value,
      metric_variance: null,
      model_name: input.name,
      organization: input.organization,
      rank: input.rank,
      sample_size: 10,
      session_count: 10,
      source_key: input.name,
    }
  }
})

const makeRow = vi.hoisted(() => {
  return function makeRow(input: {
    key: string
    name: string
    organization: string
    agentRank: number
    agentScore: number
    documentRank?: number | null
    documentRating?: number | null
    searchRank?: number | null
    searchRating?: number | null
    webdevRank?: number | null
    webdevRating?: number | null
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
        agent: makeBlock('agent', {
          kind: 'score',
          name: input.name,
          organization: input.organization,
          rank: input.agentRank,
          value: input.agentScore,
        }),
        document:
          input.documentRank === undefined
            ? null
            : makeBlock('document', {
                kind: 'rating',
                name: input.name,
                organization: input.organization,
                rank: input.documentRank,
                value: input.documentRating ?? null,
              }),
        search:
          input.searchRank === undefined
            ? null
            : makeBlock('search', {
                kind: 'rating',
                name: input.name,
                organization: input.organization,
                rank: input.searchRank,
                value: input.searchRating ?? null,
              }),
        webdev:
          input.webdevRank === undefined
            ? null
            : makeBlock('webdev', {
                kind: 'rating',
                name: input.name,
                organization: input.organization,
                rank: input.webdevRank,
                value: input.webdevRating ?? null,
              }),
      },
      aa: {
        id: input.key,
        slug: input.key,
        name: input.name,
        creator: { id: input.organization, name: input.organization },
        release_date: null,
        intelligence_index_version: 1,
        intelligence_index: 40,
        coding_index: null,
        agentic_index: null,
        intelligence_index_total_cost: null,
        cost_per_task: 0.4,
        pricing: {
          price_1m_input_tokens: 1,
          price_1m_output_tokens: 3,
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
          key: 'alpha',
          name: 'Alpha model',
          organization: 'anthropic',
          agentRank: 3,
          agentScore: 0.11,
          documentRank: 1,
          documentRating: 1516,
          webdevRank: 6,
          webdevRating: 1600,
        }),
        makeRow({
          key: 'beta',
          name: 'Beta model',
          organization: 'openai',
          agentRank: 7,
          agentScore: 0.08,
          searchRank: 1,
          searchRating: 1257,
          webdevRank: 8,
          webdevRating: 1500,
        }),
        makeRow({
          key: 'gamma',
          name: 'Gamma model',
          organization: 'xiaomi',
          agentRank: 20,
          agentScore: -0.04,
        }),
      ],
      meta: {
        generated_at: '2026-09-15T00:00:00Z',
        sources: {},
        categories_included: ['document', 'search', 'webdev'],
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
        <TaskFitPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TaskFitPage', () => {
  it('lists best-at-task models and inspects missing categories on hover', async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Task fit' })).toBeTruthy()
    expect(await screen.findByRole('heading', { name: 'Best at Agent' })).toBeTruthy()
    const alpha = screen.getByRole('link', { name: /Alpha model/ })
    expect(alpha.getAttribute('href')).toBe('/models/alpha')
    expect(screen.getByRole('link', { name: /Beta model/ })).toBeTruthy()
    expect(screen.getByRole('link', { name: /Gamma model/ })).toBeTruthy()

    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(screen.getByRole('heading', { name: 'Best at Search' })).toBeTruthy()
    expect(screen.getByRole('link', { name: /Beta model/ })).toBeTruthy()
    expect(screen.queryByRole('link', { name: /Alpha model/ })).toBeNull()

    await user.hover(screen.getByRole('link', { name: /Beta model/ }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Beta model' })).toBeTruthy()
    })
    expect(screen.getByText(/#7 · score/)).toBeTruthy()
    expect(screen.getByText(/Strongest rank is Search/)).toBeTruthy()
  })
})
