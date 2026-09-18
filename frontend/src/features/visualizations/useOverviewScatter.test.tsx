import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getOverview, type OverviewResponse, type OverviewRow } from '../../api'
import { useOverviewScatter } from './useOverviewScatter'

const makeRow = vi.hoisted(() => {
  return function makeRow(key: string): OverviewRow {
    return {
      model: {
        key,
        name: key,
        organization: 'openai',
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
          model_name: key,
          organization: 'openai',
          license: null,
          leaderboard_publish_date: '2026-09-01',
          source_key: key,
          matched_by_fold: false,
        },
        document: null,
        search: null,
        webdev: null,
      },
      aa: {
        id: key,
        slug: key,
        name: key,
        creator: { id: 'openai', name: 'openai' },
        release_date: null,
        intelligence_index_version: 1,
        intelligence_index: 40,
        coding_index: null,
        agentic_index: null,
        intelligence_index_total_cost: null,
        cost_per_task: 0.4,
        pricing: {
          price_1m_input_tokens: 1,
          price_1m_output_tokens: 2,
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
        matched_key: key,
        last_matched_at: '2026-09-15T00:00:00Z',
      },
    }
  }
})

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    getOverview: vi.fn(),
  }
})

function page(keys: string[], next: string | null): OverviewResponse {
  return {
    count: 2,
    next,
    previous: null,
    page_size: 1,
    results: keys.map(makeRow),
    meta: {
      generated_at: '2026-09-15T00:00:00Z',
      sources: {} as OverviewResponse['meta']['sources'],
      categories_included: [],
    },
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return createElement(QueryClientProvider, { client }, children)
}

describe('useOverviewScatter', () => {
  beforeEach(() => {
    vi.mocked(getOverview).mockReset()
  })

  it('plots models from every overview page, not just the first', async () => {
    vi.mocked(getOverview)
      .mockResolvedValueOnce(page(['page-one'], 'https://example.test/overview/?page=2'))
      .mockResolvedValueOnce(page(['page-two'], null))

    const { result } = renderHook(() => useOverviewScatter(), { wrapper })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(vi.mocked(getOverview).mock.calls.map((call) => call[0]?.page)).toEqual([1, 2])
    expect(result.current.data?.points.map((point) => point.key)).toEqual([
      'page-one',
      'page-two',
    ])
  })
})
