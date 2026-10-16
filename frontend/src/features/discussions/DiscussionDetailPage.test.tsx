import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { DiscussionComment, DiscussionDetailResponse } from '../../api'
import { sourceFreshnessMap } from '../../test/factories'
import { DiscussionDetailPage } from './DiscussionDetailPage'

const getDiscussion = vi.hoisted(() => vi.fn())

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return { ...actual, getDiscussion }
})

function comment(overrides: Partial<DiscussionComment> = {}): DiscussionComment {
  return {
    hn_id: 2001,
    parent_hn_id: null,
    depth: 0,
    sibling_index: 0,
    path: '000000',
    children_count: 0,
    author: 'alice',
    points: null,
    text_html: '<p>A comment</p>',
    text_plain: 'A comment',
    is_deleted: false,
    is_dead: false,
    posted_at: '2026-10-16T09:30:00Z',
    hn_url: 'https://news.ycombinator.com/item?id=2001',
    entities: [],
    ...overrides,
  }
}

function respond(
  comments: DiscussionComment[],
  threadOverrides: Partial<DiscussionDetailResponse['thread']> = {},
) {
  const response: DiscussionDetailResponse = {
    thread: {
      hn_id: 1001,
      title: 'Claude 5 is out',
      url: 'https://anthropic.com/news',
      domain: 'anthropic.com',
      author: 'poster',
      points: 900,
      num_comments: 120,
      comments_stored: comments.length,
      max_depth: 2,
      tree_truncated: false,
      rank_score: 1000,
      keywords: ['claude'],
      posted_at: '2026-10-16T08:00:00Z',
      fetched_at: '2026-10-16T11:00:00Z',
      last_synced_at: '2026-10-16T11:00:00Z',
      hn_url: 'https://news.ycombinator.com/item?id=1001',
      entities: [],
      window_days: 14,
      ...threadOverrides,
    },
    comments,
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
        counts: { threads: 1, comments: comments.length, tags: 0, entities: 52 },
        window_days: 14,
        default_page_size: 10,
        top_n: 10,
        enabled: true,
      },
      max_depth: null,
      search: null,
      entity: null,
      comments_returned: comments.length,
    },
  }
  getDiscussion.mockResolvedValue(response)
}

function renderPage(hnId = '1001') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/discussions/${hnId}`]}>
        <Routes>
          <Route element={<DiscussionDetailPage />} path="/discussions/:hnId" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DiscussionDetailPage', () => {
  it('renders the thread header and its comments', async () => {
    respond([comment(), comment({ hn_id: 2002, path: '000001', text_html: '<p>Second</p>' })])

    renderPage()

    expect(await screen.findByText('Claude 5 is out')).toBeDefined()
    expect(screen.getByText('A comment')).toBeDefined()
    expect(screen.getByText('Second')).toBeDefined()
  })

  it('renders sanitized HTML as HTML rather than as text', async () => {
    respond([
      comment({ text_html: '<p>See <a href="https://e.com">this</a> and <b>bold</b></p>' }),
    ])

    renderPage()

    // If the markup were escaped, the reader would see the tags themselves.
    const link = await screen.findByRole('link', { name: 'this' })
    expect(link.getAttribute('href')).toBe('https://e.com')
  })

  it('indents a reply by its depth', async () => {
    respond([
      comment(),
      comment({
        hn_id: 2002,
        parent_hn_id: 2001,
        depth: 1,
        path: '000000.000000',
        text_html: '<p>A reply</p>',
      }),
    ])

    renderPage()

    const reply = (await screen.findByText('A reply')).closest('article')
    expect(reply?.style.getPropertyValue('--depth')).toBe('1')
  })

  it('caps the indent so a deep thread stays readable', async () => {
    respond([comment({ depth: 40 })])

    renderPage()

    const node = (await screen.findByText('A comment')).closest('article')
    // Capped in the component rather than by the stylesheet, because a depth of
    // forty would otherwise indent the text off the screen entirely.
    expect(node?.style.getPropertyValue('--depth')).toBe('12')
  })

  it('shows the entity chips a comment earned', async () => {
    respond([
      comment({
        entities: [
          {
            slug: 'claude',
            label: 'Claude',
            kind: 'service',
            vendor: 'anthropic',
            matched_text: 'Claude',
            match_mode: 'token_prefix',
            mentions: 1,
          },
        ],
      }),
    ])

    renderPage()

    expect(await screen.findByText('Claude')).toBeDefined()
  })

  it('explains a withheld comment instead of rendering it empty', async () => {
    respond([comment({ is_deleted: true, author: null, text_html: '', text_plain: '' })])

    renderPage()

    expect(await screen.findByText(/author deleted this comment/i)).toBeDefined()
    expect(screen.getByText('deleted')).toBeDefined()
  })

  it('warns when the thread was truncated, with both counts', async () => {
    respond([comment()], { num_comments: 1036, comments_stored: 600, tree_truncated: true })

    renderPage()

    expect(await screen.findByText(/truncated by the ingest cap/i)).toBeDefined()

    // The reported total appears **twice**: beside the stored count in the stat
    // strip, and in the warning. Showing both is the point -- either number alone
    // misleads about how much of the discussion is here.
    expect(screen.getAllByText(/1,036/).length).toBeGreaterThanOrEqual(2)
  })

  it('says so when no comments are stored, rather than showing nothing', async () => {
    respond([])

    renderPage()

    expect(await screen.findByText('No comments stored for this thread.')).toBeDefined()
  })

  it('links back to the thread on Hacker News', async () => {
    respond([comment()])

    renderPage()

    const link = await screen.findByRole('link', { name: /open on hacker news/i })
    expect(link.getAttribute('href')).toBe('https://news.ycombinator.com/item?id=1001')
  })

  it('requests the id from the route', async () => {
    respond([comment()])

    renderPage('4242')

    expect(getDiscussion).toHaveBeenCalledWith('4242', {}, expect.anything())
  })
})
