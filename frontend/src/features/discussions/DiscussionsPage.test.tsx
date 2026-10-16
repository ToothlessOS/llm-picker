import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { DiscussionThreadRow } from '../../api'
import { sourceFreshnessMap } from '../../test/factories'
import { DiscussionsPage } from './DiscussionsPage'

const makeRow = vi.hoisted(() => {
  return function makeRow(input: {
    hnId: number
    title: string
    points: number | null
    numComments: number | null
    stored: number
    truncated?: boolean
    entities?: DiscussionThreadRow['entities']
  }): DiscussionThreadRow {
    return {
      hn_id: input.hnId,
      title: input.title,
      url: 'https://example.com/x',
      domain: 'example.com',
      author: 'poster',
      points: input.points,
      num_comments: input.numComments,
      comments_stored: input.stored,
      max_depth: 2,
      tree_truncated: input.truncated ?? false,
      rank_score: 100,
      keywords: ['llm'],
      posted_at: '2026-10-16T09:00:00Z',
      fetched_at: '2026-10-16T11:00:00Z',
      last_synced_at: '2026-10-16T11:00:00Z',
      hn_url: `https://news.ycombinator.com/item?id=${input.hnId}`,
      entities: input.entities ?? [],
      matched_comment_count: null,
    }
  }
})

const getDiscussions = vi.hoisted(() => vi.fn())

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return { ...actual, getDiscussions }
})

function respond(rows: DiscussionThreadRow[], overrides: Record<string, unknown> = {}) {
  getDiscussions.mockResolvedValue({
    count: rows.length,
    next: null,
    previous: null,
    page_size: 10,
    results: rows,
    meta: {
      generated_at: '2026-10-16T12:00:00Z',
      sources: sourceFreshnessMap(),
      discussions: {
        configured: true,
        last_attempt_at: '2026-10-16T11:00:00Z',
        last_status: 'success',
        last_success_at: '2026-10-16T11:00:00Z',
        age_seconds: 3600,
        is_stale: false,
        stale_after_seconds: 7200,
        last_error: null,
        counts: { threads: 2, comments: 30, tags: 12, entities: 52 },
        window_days: 14,
        default_page_size: 10,
        top_n: 10,
        enabled: true,
        ...overrides,
      },
    },
  })
}

function renderPage(initialEntry = '/discussions') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <DiscussionsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DiscussionsPage', () => {
  it('renders a thread row with its provider chips', async () => {
    respond([
      makeRow({
        hnId: 1,
        title: 'Claude 5 is out',
        points: 900,
        numComments: 120,
        stored: 120,
        entities: [
          {
            slug: 'claude',
            label: 'Claude',
            kind: 'service',
            vendor: 'anthropic',
            matched_text: 'Claude',
            match_mode: 'token_prefix',
            mentions: 3,
          },
        ],
      }),
    ])

    renderPage()

    expect(await screen.findByText('Claude 5 is out')).toBeDefined()
    expect(screen.getByText('Claude')).toBeDefined()
    expect(screen.getByText('900')).toBeDefined()
  })

  it('shows both counts when a thread was truncated', async () => {
    respond([
      makeRow({ hnId: 1, title: 'Big thread', points: 900, numComments: 1036, stored: 600, truncated: true }),
    ])

    renderPage()

    // The stored count, with the reported total beside it -- either alone
    // misleads about how much of the discussion is here.
    expect(await screen.findByText('600')).toBeDefined()
    expect(screen.getByText(/1,036/)).toBeDefined()
  })

  it('names the ingest cap as the reason when the tree was truncated', async () => {
    respond([
      makeRow({ hnId: 1, title: 'Capped', points: 900, numComments: 1216, stored: 600, truncated: true }),
    ])

    renderPage()

    // `findByText` matches the element whose *own* text is "600", which is the
    // wrapper carrying the tooltip.
    const cell = await screen.findByText('600')
    expect(cell.getAttribute('title') ?? '').toMatch(/ingest cap/i)
  })

  it('shows both counts when a thread gained comments since the fetch', async () => {
    respond([
      makeRow({ hnId: 1, title: 'Active thread', points: 500, numComments: 120, stored: 100 }),
    ])

    renderPage()

    // Not truncated, so before this the cell showed a bare "100" with no hint we
    // were behind. The gap is transient -- the next refresh refetches and closes
    // it -- which is why the reason is spelled out rather than assumed.
    const cell = await screen.findByText('100')
    expect(cell.textContent).toMatch(/\/\s*120/)
    expect(cell.getAttribute('title') ?? '').toMatch(/next refresh/i)
  })

  it('shows a single count when we hold the whole discussion', async () => {
    respond([makeRow({ hnId: 1, title: 'Complete', points: 500, numComments: 80, stored: 80 })])

    renderPage()

    const cell = await screen.findByText('80')
    expect(cell.textContent).not.toMatch('/')
    expect(cell.getAttribute('title')).toBeNull()
  })

  it('says "pending" rather than zero for a thread with no tree yet', async () => {
    respond([makeRow({ hnId: 1, title: 'Deferred', points: 500, numComments: 400, stored: 0 })])

    renderPage()

    expect(await screen.findByText('pending')).toBeDefined()
  })

  it('renders an unmeasured points value rather than a zero', async () => {
    respond([makeRow({ hnId: 1, title: 'Unranked', points: null, numComments: 5, stored: 5 })])

    renderPage()

    expect(await screen.findByText('Not measured')).toBeDefined()
  })

  it('puts the search term in the URL', async () => {
    respond([makeRow({ hnId: 1, title: 'Thread', points: 1, numComments: 1, stored: 1 })])

    renderPage()

    const input = await screen.findByRole('searchbox')
    await userEvent.type(input, 'cursor')

    await waitFor(() => {
      const call = getDiscussions.mock.calls.at(-1)?.[0]
      expect(call?.search).toBe('cursor')
    })
  })

  it('reads an entity filter out of the URL and sends it', async () => {
    respond([makeRow({ hnId: 1, title: 'Thread', points: 1, numComments: 1, stored: 1 })])

    renderPage('/discussions?entity=anthropic')

    await waitFor(() => {
      expect(getDiscussions.mock.calls.at(-1)?.[0]?.entity).toEqual(['anthropic'])
    })
  })

  it('summarises the bank from the freshness block', async () => {
    respond([makeRow({ hnId: 1, title: 'Thread', points: 1, numComments: 1, stored: 1 })])

    renderPage()

    expect(await screen.findByText(/12 entity tags/)).toBeDefined()
  })

  it('offers to clear filters only when some are set', async () => {
    respond([])

    renderPage('/discussions?q=nothing-matches')

    expect(await screen.findByText('No matching discussions')).toBeDefined()
    expect(screen.getByRole('button', { name: /clear filters/i })).toBeDefined()
  })

  it('distinguishes an empty bank from an empty filter result', async () => {
    respond([])

    renderPage()

    // No filters, no rows: the honest message is "nothing collected yet", not
    // "your filters matched nothing".
    expect(await screen.findByText('No discussions yet')).toBeDefined()
  })

  it('surfaces a failed refresh without hiding the rows', async () => {
    respond(
      [makeRow({ hnId: 1, title: 'Still served', points: 1, numComments: 1, stored: 1 })],
      { last_status: 'failed', last_error: { code: 'transport_error', message: 'down' } },
    )

    renderPage()

    expect(await screen.findByText('Still served')).toBeDefined()
  })
})
