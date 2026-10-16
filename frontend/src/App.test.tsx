import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { MetadataResponse } from './api'
import { sourceFreshnessMap } from './test/factories'
import App from './App'

const getDiscussion = vi.hoisted(() => vi.fn())

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  const empty = { count: 0, next: null, previous: null, page_size: 10, results: [] }
  const discussions = {
    configured: true,
    last_attempt_at: null,
    last_status: null,
    last_success_at: null,
    age_seconds: null,
    is_stale: false,
    stale_after_seconds: 7200,
    last_error: null,
    counts: { threads: 0, comments: 0, tags: 0, entities: 0 },
    window_days: 14,
    default_page_size: 10,
    top_n: 10,
    enabled: true,
  }
  const meta = {
    generated_at: '2026-10-16T12:00:00Z',
    sources: sourceFreshnessMap(),
  }
  const metadata: MetadataResponse = {
    sources: sourceFreshnessMap(),
    counts: {
      lmarena_entries: 0,
      lmarena_agent_entries: 0,
      complete_agent_entries: 0,
      aa_models: 0,
      aa_models_retained: 0,
      matches: 0,
      unmatched_records: 0,
    },
    discussions,
    categories: [],
    matching: {},
    recent_runs: [],
    config: { harness_fold_enabled: true, stale_after_seconds: 50_400 },
    attribution: { artificial_analysis: '', lmarena: '' },
    meta,
  }

  return {
    ...actual,
    getDiscussion,
    getDiscussions: vi.fn().mockResolvedValue({ ...empty, meta: { ...meta, discussions } }),
    getDiscussionEntities: vi.fn().mockResolvedValue({
      results: [],
      meta: { ...meta, discussions, kinds: ['vendor', 'service'] },
    }),
    getMetadata: vi.fn().mockResolvedValue(metadata),
    getOverview: vi.fn().mockResolvedValue({ ...empty, page_size: 200, meta }),
  }
})

function renderApp(entry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('routing', () => {
  it('resolves /discussions/map to the map, not to a thread called "map"', async () => {
    // React Router ranks a static segment above a dynamic one, so this works —
    // but if that ranking ever changes, `discussions/:hnId` would win, the page
    // would ask the API for a thread with the id `map`, and it would 404. The
    // assertion that catches it is the second one: no such request was made.
    renderApp('/discussions/map')

    expect(await screen.findByLabelText('Search this thread')).toBeTruthy()
    expect(getDiscussion).not.toHaveBeenCalled()
  })

  it('still resolves /discussions/<id> to the thread itself', async () => {
    getDiscussion.mockResolvedValue({
      thread: {
        hn_id: 12345,
        title: 'A thread',
        url: null,
        domain: null,
        author: null,
        points: null,
        num_comments: null,
        comments_stored: 0,
        max_depth: 0,
        tree_truncated: false,
        rank_score: null,
        keywords: [],
        posted_at: '2026-10-16T08:00:00Z',
        fetched_at: null,
        last_synced_at: '2026-10-16T08:00:00Z',
        hn_url: 'https://news.ycombinator.com/item?id=12345',
        entities: [],
        window_days: 14,
      },
      comments: [],
      meta: {
        generated_at: '2026-10-16T12:00:00Z',
        sources: sourceFreshnessMap(),
        discussions: {
          configured: true,
          last_attempt_at: null,
          last_status: null,
          last_success_at: null,
          age_seconds: null,
          is_stale: false,
          stale_after_seconds: 7200,
          last_error: null,
          counts: { threads: 0, comments: 0, tags: 0, entities: 0 },
          window_days: 14,
          default_page_size: 10,
          top_n: 10,
          enabled: true,
        },
        max_depth: null,
        search: null,
        entity: null,
        comments_returned: 0,
      },
    })

    renderApp('/discussions/12345')

    expect(await screen.findByText('A thread')).toBeTruthy()
    expect(getDiscussion).toHaveBeenCalledWith('12345', {}, expect.anything())
  })
})
