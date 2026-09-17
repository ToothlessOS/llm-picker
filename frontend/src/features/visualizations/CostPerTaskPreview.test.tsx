import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { OverviewRow } from '../../api'
import { CostPerTaskPreview } from './CostPerTaskPreview'

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    getOverview: vi.fn().mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      page_size: 200,
      results: [
        {
          model: {
            key: 'cheap',
            name: 'Cheap task',
            organization: 'xiaomi',
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
              model_name: 'Cheap task',
              organization: 'xiaomi',
              license: null,
              leaderboard_publish_date: '2026-09-01',
              source_key: 'cheap',
              matched_by_fold: false,
            },
            document: null,
            search: null,
            webdev: null,
          },
          aa: {
            id: 'cheap',
            slug: 'cheap',
            name: 'Cheap task',
            creator: { id: 'xiaomi', name: 'xiaomi' },
            release_date: null,
            intelligence_index_version: 1,
            intelligence_index: 40,
            coding_index: null,
            agentic_index: null,
            intelligence_index_total_cost: null,
            cost_per_task: 0.1,
            pricing: {
              price_1m_input_tokens: 1,
              price_1m_output_tokens: 3,
              price_1m_cache_hit_tokens: 0,
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
            matched_key: 'cheap',
            last_matched_at: '2026-09-15T00:00:00Z',
          },
        } satisfies OverviewRow,
      ],
      meta: {
        generated_at: '2026-09-15T00:00:00Z',
        sources: {},
        categories_included: [],
      },
    }),
  }
})

describe('CostPerTaskPreview', () => {
  it('says the stack is a list-price mix rather than actual usage', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <CostPerTaskPreview />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('1 model · list-price mix, not usage')).toBeTruthy()
  })
})
