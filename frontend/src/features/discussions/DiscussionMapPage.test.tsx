import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  DiscussionComment,
  DiscussionDetailResponse,
  DiscussionEntitiesResponse,
  DiscussionListResponse,
} from '../../api'
import { IntersectionObserverStub } from '../../test/intersectionObserver'
import {
  commentTree,
  discussionComment,
  discussionThreadRow,
  entityRef,
  sourceFreshnessMap,
  vendorRef,
  type CommentSpec,
} from '../../test/factories'
import { DiscussionMapPage } from './DiscussionMapPage'

const getDiscussion = vi.hoisted(() => vi.fn())
const getDiscussions = vi.hoisted(() => vi.fn())
const getDiscussionEntities = vi.hoisted(() => vi.fn())

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return { ...actual, getDiscussion, getDiscussions, getDiscussionEntities }
})

const THREAD_ID = 1001

function detailMeta(comments: number): DiscussionDetailResponse['meta'] {
  return {
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
      counts: { threads: 1, comments, tags: 0, entities: 52 },
      window_days: 14,
      default_page_size: 10,
      top_n: 10,
      enabled: true,
    },
    max_depth: null,
    search: null,
    entity: null,
    comments_returned: comments,
  }
}

/** Answer with a nested spec, flattened the way the API returns it. */
function respond(
  specs: readonly CommentSpec[],
  threadOverrides: Partial<DiscussionDetailResponse['thread']> = {},
) {
  return respondWith(commentTree(specs), threadOverrides)
}

function respondWith(
  comments: DiscussionComment[],
  threadOverrides: Partial<DiscussionDetailResponse['thread']> = {},
) {
  getDiscussion.mockResolvedValue({
    thread: {
      hn_id: THREAD_ID,
      title: 'Claude 5 is out',
      url: 'https://anthropic.com/news',
      domain: 'anthropic.com',
      author: 'poster',
      points: 900,
      num_comments: comments.length,
      comments_stored: comments.length,
      max_depth: 3,
      tree_truncated: false,
      rank_score: 1000,
      keywords: ['claude'],
      posted_at: '2026-10-16T08:00:00Z',
      fetched_at: '2026-10-16T11:00:00Z',
      last_synced_at: '2026-10-16T11:00:00Z',
      hn_url: `https://news.ycombinator.com/item?id=${THREAD_ID}`,
      entities: [],
      window_days: 14,
      ...threadOverrides,
    },
    comments,
    meta: detailMeta(comments.length),
  })
}

function respondWithVocabulary() {
  const response: DiscussionEntitiesResponse = {
    results: [
      {
        slug: 'anthropic',
        label: 'Anthropic',
        kind: 'vendor',
        vendor: null,
        lmarena_organization: 'anthropic',
        aliases: ['Anthropic'],
        thread_count: 74,
        note: null,
      },
      {
        slug: 'openai',
        label: 'OpenAI',
        kind: 'vendor',
        vendor: null,
        lmarena_organization: 'openai',
        aliases: ['OpenAI'],
        thread_count: 90,
        note: null,
      },
      {
        slug: 'claude',
        label: 'Claude',
        kind: 'service',
        vendor: 'anthropic',
        lmarena_organization: null,
        aliases: ['Claude'],
        thread_count: 90,
        note: null,
      },
    ],
    meta: { ...detailMeta(0), kinds: ['vendor', 'service'] },
  }
  getDiscussionEntities.mockResolvedValue(response)
}

function respondWithRail() {
  const response: DiscussionListResponse = {
    count: 1,
    next: null,
    previous: null,
    page_size: 20,
    results: [discussionThreadRow({ hn_id: THREAD_ID })],
    meta: detailMeta(0),
  }
  getDiscussions.mockResolvedValue(response)
}

function LocationProbe() {
  const location = useLocation()
  return <span data-testid="location">{location.search}</span>
}

function renderPage(entry = `/discussions/map?thread=${THREAD_ID}`) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <LocationProbe />
        <Routes>
          <Route element={<DiscussionMapPage />} path="/discussions/map" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** A map row by comment id — the map is a graphic, so its marks are queried directly. */
function row(id: number): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-row-id="${id}"]`)
}

function mapRows(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>('[data-row-id]')]
}

function readerArticles(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>('.reader article[data-hn-id]')]
}

function articleFor(id: number): HTMLElement {
  const found = readerArticles().find((element) => element.dataset.hnId === String(id))
  if (!found) throw new Error(`no reader article for comment ${id}`)
  return found
}

/**
 * Wait until the thread query has painted.
 *
 * Waiting on the rail's "Threads" heading is not enough — that query resolves
 * independently of the thread's, so asserting on map rows or reader articles
 * straight after is a race. The reader is the reliable signal: it renders the
 * thread's comments as soon as the detail response lands.
 */
async function waitForThread(text: string | RegExp) {
  await screen.findByText(text)
}

const THREE_ROOTS: CommentSpec[] = [
  { id: 1, text: 'alpha' },
  { id: 2, text: 'beta' },
  { id: 3, text: 'gamma' },
]

beforeEach(() => {
  respondWithRail()
  respondWithVocabulary()
})

describe('DiscussionMapPage', () => {
  it('draws a row per comment and lists the threads beside it', async () => {
    respond(THREE_ROOTS)

    renderPage()

    expect(await screen.findByText('Threads')).toBeDefined()
    await waitForThread('alpha')
    expect(mapRows()).toHaveLength(3)
  })

  it('never asks the server to trim the tree', async () => {
    // The architectural guard. `?max_depth`, `?search` and `?entity` on the
    // detail endpoint cut the comment array, which would leave children whose
    // parents are missing — and the map's whole encoding is a comment's position
    // in the thread. No screenshot would catch that regression; this does.
    respond(THREE_ROOTS)

    renderPage()

    await waitForThread('alpha')
    expect(getDiscussion).toHaveBeenCalledWith(THREAD_ID, {}, expect.anything())
  })

  describe('the reader follows the map', () => {
    it('shows the whole thread until something is selected', async () => {
      respond(THREE_ROOTS)

      renderPage()

      expect(await screen.findByText('alpha')).toBeDefined()
      expect(screen.getByText('beta')).toBeDefined()
      expect(screen.getByText('gamma')).toBeDefined()
    })

    it('scopes to a selected branch, and pins the selection on top', async () => {
      // Rules 2 to 4 at once: selecting a first-layer block reads only its
      // replies, and the block itself stays at the top.
      respond([
        { id: 1, text: 'alpha', children: [{ id: 2, text: 'beta' }] },
        { id: 3, text: 'gamma' },
      ])
      renderPage()
      await waitForThread('alpha')

      fireEvent.click(row(1) as HTMLElement)

      const articles = readerArticles()
      expect(articles[0].textContent).toContain('alpha')
      expect(articles[0].classList.contains('is-focus')).toBe(true)
      expect(screen.getByText('beta')).toBeDefined()
      // The sibling branch is out of scope entirely.
      expect(screen.queryByText('gamma')).toBeNull()
      expect(screen.getByTestId('location').textContent).toContain('comment=1')
    })

    it('scopes to a deeper block the same way', async () => {
      respond([
        {
          id: 1,
          text: 'alpha',
          children: [
            { id: 2, text: 'beta', children: [{ id: 4, text: 'delta' }] },
            { id: 3, text: 'gamma' },
          ],
        },
      ])
      renderPage()
      await waitForThread('beta')

      fireEvent.click(row(2) as HTMLElement)

      expect(readerArticles()[0].textContent).toContain('beta')
      expect(screen.getByText('delta')).toBeDefined()
      expect(screen.queryByText('gamma')).toBeNull()
    })

    it('goes back to the whole thread when the focus is cleared', async () => {
      respond([
        { id: 1, text: 'alpha', children: [{ id: 2, text: 'beta' }] },
        { id: 3, text: 'gamma' },
      ])
      renderPage(`/discussions/map?thread=${THREAD_ID}&comment=1`)
      await waitForThread('beta')

      fireEvent.click(screen.getByRole('button', { name: /back to thread/i }))

      expect(screen.getByText('gamma')).toBeDefined()
      expect(screen.getByTestId('location').textContent).not.toContain('comment=')
    })
  })

  it('highlights the comment being read in both panes', async () => {
    // Rule 5. The reader reports its position; the map rings the same row.
    respond(THREE_ROOTS)
    renderPage()
    await waitForThread('beta')

    const observer = IntersectionObserverStub.latest
    expect(observer).not.toBeNull()
    act(() => observer?.enter(articleFor(2)))

    await waitFor(() => {
      expect(row(2)?.classList.contains('is-reading')).toBe(true)
    })
    expect(articleFor(2).classList.contains('is-active')).toBe(true)
    expect(row(1)?.classList.contains('is-reading')).toBe(false)
  })

  it('pins the focused branch above the replies rather than over them', async () => {
    // The bug this replaces: the pinned block was `position: sticky` *inside* the
    // scrolling region, so the replies slid underneath it and were painted behind
    // the pinned comment. As sibling regions they cannot overlap at all, which is
    // what this asserts — the pinned comment is not in the scrolling layer, and
    // the replies are not outside it.
    respond([
      { id: 1, text: 'alpha', children: [{ id: 2, text: 'beta' }] },
      { id: 3, text: 'gamma' },
    ])

    renderPage(`/discussions/map?thread=${THREAD_ID}&comment=1`)
    await waitForThread('beta')

    const pinned = document.querySelector('.reader__pinned')
    expect(pinned).not.toBeNull()
    expect(pinned?.querySelector('[data-hn-id="1"]')).not.toBeNull()
    expect(pinned?.closest('.reader__scroll')).toBeNull()
    expect(document.querySelector('.reader__scroll [data-hn-id="1"]')).toBeNull()
    expect(document.querySelector('.reader__scroll [data-hn-id="2"]')).not.toBeNull()
  })

  it('keeps Details at the very top, above a pinned branch', async () => {
    // It is a property of the whole pane rather than of whatever is selected in
    // it, so pinning a branch must not push it down — and it must not scroll away
    // while reading, which is what put it inside the scrolling region originally.
    respond([
      { id: 1, text: 'alpha', children: [{ id: 2, text: 'beta' }] },
      { id: 3, text: 'gamma' },
    ])

    renderPage(`/discussions/map?thread=${THREAD_ID}&comment=1`)
    await waitForThread('beta')

    const reader = document.querySelector('.reader')
    expect([...(reader?.children ?? [])].map((el) => el.className)).toEqual([
      'reader__details',
      'reader__pinned',
      'reader__scroll',
    ])
    expect(document.querySelector('.reader__details')?.closest('.reader__scroll')).toBeNull()
  })

  it('keeps Details at the top when nothing is pinned, too', async () => {
    respond(THREE_ROOTS)

    renderPage()

    await waitForThread('alpha')
    const reader = document.querySelector('.reader')
    expect([...(reader?.children ?? [])].map((el) => el.className)).toEqual([
      'reader__details',
      'reader__scroll',
    ])
  })

  it('points the map at the branch containing what is being read', async () => {
    // Coordination across the drawn depth. The map is opened to the top level
    // only, so comments 3 and 4 have no row; scrolling the reader onto 4 must
    // still move the map, by marking the collapsed bar that contains it. Without
    // this the map stops tracking partway down any large thread.
    respond([
      { id: 1, text: 'alpha', children: [{ id: 2, text: 'beta', children: [{ id: 3, text: 'gamma', children: [{ id: 4, text: 'delta' }] }] }] },
    ])

    renderPage(`/discussions/map?thread=${THREAD_ID}&depth=roots`)
    await waitForThread('delta')

    expect(row(4)).toBeNull()

    const observer = IntersectionObserverStub.latest
    act(() => observer?.enter(articleFor(4)))

    await waitFor(() => {
      expect(row(2)?.classList.contains('is-reading')).toBe(true)
    })
  })

  it('leaves the map alone while it is being scrolled by hand', async () => {
    // Only the reader drives the map. If the map also drove the reader, the two
    // would chase each other, and a reader scrolling the map to look around
    // would lose their place in the text.
    respond([
      { id: 1, text: 'alpha', children: [{ id: 2, text: 'beta' }] },
    ])

    renderPage(`/discussions/map?thread=${THREAD_ID}&comment=2`)
    await waitForThread('beta')

    const map = screen.getByTestId('discussion-map')
    fireEvent.scroll(map, { target: { scrollTop: 400 } })

    // The reader's position is untouched: still the pinned branch, still 0 replies.
    expect(document.querySelector('.reader__pinned')).not.toBeNull()
    expect(screen.getByText(/0 replies to this comment/)).toBeDefined()
  })

  describe('search', () => {
    it('marks the term in the reader and rings the block in the map', async () => {
      respond([
        { id: 1, text: 'alpha', children: [{ id: 2, text: 'prefers beta here' }] },
        { id: 3, text: 'gamma' },
      ])

      renderPage(`/discussions/map?thread=${THREAD_ID}&q=beta`)

      await waitFor(() => {
        expect(document.querySelectorAll('mark.comment-hl')).toHaveLength(1)
      })
      const marks = document.querySelectorAll('mark.comment-hl')
      expect(marks[0].textContent).toBe('beta')
      expect(row(2)?.classList.contains('is-hit')).toBe(true)
      expect(row(1)?.classList.contains('is-hit')).toBe(false)
    })

    it('marks case-insensitively and re-marks without nesting', async () => {
      respond([{ id: 1, text: 'Beta and BETA and beta' }])

      renderPage(`/discussions/map?thread=${THREAD_ID}&q=BETA`)

      await waitFor(() => {
        expect(document.querySelectorAll('mark.comment-hl')).toHaveLength(3)
      })
      expect(document.querySelectorAll('mark mark')).toHaveLength(0)
      // The text is intact around the marks, and capitalisation is preserved.
      expect(readerArticles()[0].textContent).toContain('Beta and BETA and beta')
    })

    it('does not match a term that only appears in markup', async () => {
      // The reason `matchesSearch` reads `text_plain`: `q=href` must not light up
      // every post containing a link, and it must not mark attribute text.
      respondWith([
        discussionComment({
          hn_id: 1,
          text_html: '<p>See <a href="https://example.com/claude">the docs</a></p>',
          text_plain: 'See the docs',
        }),
      ])

      renderPage(`/discussions/map?thread=${THREAD_ID}&q=href`)

      await waitForThread(/See/)
      expect(document.querySelectorAll('mark.comment-hl')).toHaveLength(0)
      // Nothing matched, so nothing is drawn — the user asked a question the
      // thread has no answer to, and an empty map says so.
      expect(mapRows()).toHaveLength(0)
      expect(screen.getByRole('link', { name: 'the docs' }).getAttribute('href')).toBe(
        'https://example.com/claude',
      )
    })
  })

  describe('entity filters', () => {
    it('rolls a service up to its vendor', async () => {
      // `?entity=anthropic` must keep a Claude-tagged comment bright — mirroring
      // the endpoint's own `slug__in | vendor__slug__in`.
      respond([
        { id: 1, text: 'about claude', entities: [entityRef()] },
        { id: 2, text: 'about gemini', entities: [vendorRef('google', 'Google')] },
      ])

      renderPage(`/discussions/map?thread=${THREAD_ID}&entity=anthropic`)

      await waitForThread('about claude')
      expect(row(1)).not.toBeNull()
      expect(row(1)?.classList.contains('is-dimmed')).toBe(false)
      // A comment with nothing to do with the filter is not drawn at all.
      expect(row(2)).toBeNull()
    })

    it('stops at six active filters, and says why', async () => {
      respond(THREE_ROOTS)

      renderPage(
        `/discussions/map?thread=${THREAD_ID}&entity=anthropic,openai,claude,a,b,c`,
      )

      await waitForThread('alpha')
      expect((screen.getByLabelText('Provider') as HTMLSelectElement).disabled).toBe(true)
      expect((screen.getByLabelText('Service') as HTMLSelectElement).disabled).toBe(true)
      expect(screen.getByText(/most the colour legend can tell apart/i)).toBeDefined()
    })

    it('shows a removable chip per active filter', async () => {
      respond(THREE_ROOTS)

      renderPage(`/discussions/map?thread=${THREAD_ID}&entity=anthropic`)

      await waitForThread('alpha')
      fireEvent.click(screen.getByRole('button', { name: /anthropic/i }))

      expect(screen.getByTestId('location').textContent).not.toContain('entity=')
    })
  })

  describe('the reader stays bounded', () => {
    it('renders a page at a time and says how much is left', async () => {
      respond(Array.from({ length: 250 }, (_, index) => ({ id: index + 1 })))

      renderPage()

      await waitFor(() => expect(readerArticles()).toHaveLength(200))

      fireEvent.click(screen.getByRole('button', { name: /show .* more/i }))

      expect(readerArticles()).toHaveLength(250)
    })
  })

  describe('deep links', () => {
    it('pins the comment named by a path', async () => {
      respond([
        { id: 1, text: 'alpha', children: [{ id: 2, text: 'beta' }] },
        { id: 3, text: 'gamma' },
      ])

      renderPage(`/discussions/map?thread=${THREAD_ID}&comment=000000.000000`)

      await waitForThread('beta')
      expect(readerArticles()[0].textContent).toContain('beta')
      expect(screen.queryByText('alpha')).toBeNull()
    })

    it('falls back to the whole thread when the link is stale', async () => {
      // A URL shared before a refetch is the ordinary way to arrive at this, so
      // it has to degrade rather than blank the reader.
      respond(THREE_ROOTS)

      renderPage(`/discussions/map?thread=${THREAD_ID}&comment=999999`)

      expect(
        await screen.findByText(/That comment is not in the current data/i),
      ).toBeDefined()
      expect(screen.getByText('alpha')).toBeDefined()
    })
  })

  it('asks for a thread when none is chosen', async () => {
    respond(THREE_ROOTS)

    renderPage('/discussions/map')

    expect(await screen.findByText(/No thread selected/i)).toBeDefined()
    expect(getDiscussion).not.toHaveBeenCalled()
  })

  it('leaves out of the reader what the page already says twice', async () => {
    // The stat grid and the thread's tag cloud were removed from the reader: the
    // points, count and age are in the rail row *and* the toolbar, and the
    // thread's entities are the map legend, listed there with the colours they
    // are drawn in. On a busy thread the two together were ~150px of the reading
    // pane. Pinned so they cannot creep back.
    respond([{ id: 1, text: 'alpha' }], { entities: [entityRef()] })

    renderPage()

    await waitForThread('alpha')
    expect(screen.getByRole('heading', { name: 'Details' })).toBeDefined()
    expect(document.querySelector('.reader .stat-strip')).toBeNull()
    expect(document.querySelector('.reader .entity-chips')).toBeNull()
    // What exists nowhere else on the page is still here.
    expect(screen.getByRole('link', { name: /open on hacker news/i })).toBeDefined()
    expect(screen.getByText(/submitted by/)).toBeDefined()
  })

  it('keeps a comment\u2019s own entity tags, which the legend cannot say', async () => {
    // The *thread's* tags were the redundant ones. A single comment's tag is the
    // only place that comment's entity is named in words rather than as a colour
    // band, so it stays.
    respond([{ id: 1, text: 'alpha', entities: [entityRef()] }])

    renderPage()

    await waitForThread('alpha')
    expect(document.querySelector('.reader .entity-chips')).not.toBeNull()
  })

  it('warns once when the stored tree was truncated', async () => {
    respond([{ id: 1, text: 'alpha' }], {
      comments_stored: 600,
      num_comments: 1036,
      tree_truncated: true,
    })

    renderPage()

    const warnings = await screen.findAllByText(/truncated by the ingest cap/i)
    expect(warnings).toHaveLength(1)
  })
})
