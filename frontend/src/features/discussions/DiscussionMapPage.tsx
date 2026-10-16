import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'

import {
  getDiscussion,
  getDiscussionEntities,
  type DiscussionComment,
} from '../../api'
import { useDiscussionMapState } from '../../app/useDiscussionMapState'
import { PageHeader } from '../../components/PageHeader'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'
import { DiscussionMap } from './DiscussionMap'
import { DiscussionRail } from './DiscussionRail'
import { DiscussionReader } from './DiscussionReader'
import { MapToolbar, type MapSummary } from './MapToolbar'
import {
  buildDiscussionTree,
  defaultDepthMode,
  layoutMap,
  nearestDrawnRow,
  resolveFocus,
  type MapOptions,
} from './discussionTree'

const NOTHING: ReadonlySet<number> = new Set()
/** A stable empty list, so `buildDiscussionTree` is not re-run for a missing thread. */
const NO_COMMENTS: readonly DiscussionComment[] = []

/**
 * One thread as a map, with the reader beside it.
 *
 * The page owns every piece of state and both queries; the three panes below it
 * are presentational. Two things are worth knowing about the wiring:
 *
 * * **The detail request is unfiltered** — `getDiscussion(hnId, {})`. The endpoint
 *   accepts `?max_depth`, `?search` and `?entity` that *trim the comment array*,
 *   and any of them would leave children whose parents are missing. The map's
 *   entire encoding is a comment's position in the thread, so a trimmed response
 *   does not degrade the picture, it destroys it. Filtering happens here, against
 *   the whole tree, where the structure is intact.
 * * **`useMemo` on both the options and the layout** is load-bearing, not
 *   tidiness. `layoutMap` allocates a row per visible comment, so rebuilding it
 *   on every render would walk 1,500 objects per keystroke.
 */
export function DiscussionMapPage() {
  const location = useLocation()
  const {
    state,
    selectThread,
    focusComment,
    patchQuery,
    patchView,
    toggleEntity,
    clearFilters,
  } = useDiscussionMapState()

  const entitiesQuery = useQuery({
    queryKey: ['discussion-entities'],
    queryFn: ({ signal }) => getDiscussionEntities({ signal }),
    staleTime: 300_000,
  })

  const threadQuery = useQuery({
    queryKey: ['discussion', state.thread],
    queryFn: ({ signal }) => getDiscussion(state.thread as number, {}, { signal }),
    enabled: state.thread !== null,
    staleTime: 300_000,
    refetchInterval: 300_000,
  })

  const thread = threadQuery.data?.thread
  const comments = threadQuery.data?.comments ?? NO_COMMENTS
  const tree = useMemo(() => buildDiscussionTree(comments), [comments])

  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(NOTHING)
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(NOTHING)
  const [readingId, setReadingId] = useState<number | null>(null)
  const [paneWidth, setPaneWidth] = useState(600)

  // Collapse state belongs to a thread, so choosing another one starts clean.
  // Adjusted during render, guarded so it cannot loop.
  const [lastThread, setLastThread] = useState<number | null>(state.thread)
  if (lastThread !== state.thread) {
    setLastThread(state.thread)
    setCollapsed(NOTHING)
    setExpanded(NOTHING)
    setReadingId(null)
  }

  const focusId = useMemo(
    () => resolveFocus(tree, state.comment),
    [tree, state.comment],
  )

  const depth = state.depth ?? defaultDepthMode(comments.length)

  const options = useMemo<MapOptions>(
    () => ({
      depth,
      collapsed,
      expanded,
      focusId,
      search: state.search,
      entities: state.entities,
      hideQuietBranches: state.hideQuiet,
    }),
    [
      depth,
      collapsed,
      expanded,
      focusId,
      state.search,
      state.entities,
      state.hideQuiet,
    ],
  )

  const layout = useMemo(
    () => layoutMap(tree, options, paneWidth),
    [tree, options, paneWidth],
  )

  /**
   * What the map points at, and scrolls to keep in view.
   *
   * The reading position wins over the focus once the reader has reported one —
   * the focus is where you started, the reading position is where you are — and
   * either is mapped to the nearest row that is actually drawn, since a comment
   * nested below the drawn depth has no row of its own. See `nearestDrawnRow`.
   */
  const activeId = useMemo(
    () => nearestDrawnRow(tree, layout, readingId ?? focusId),
    [tree, layout, readingId, focusId],
  )

  const handleGeometry = useCallback((width: number) => {
    // Ignored below a sane minimum: a pane mid-layout reports 0, and a layout
    // built against 0 would clamp every block to the minimum width.
    if (width >= 120) setPaneWidth(width)
  }, [])

  const handleToggle = useCallback((id: number) => {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const entities = entitiesQuery.data?.results ?? []
  const summary: MapSummary | null = thread
    ? {
        posts: comments.length,
        roots: layout.rootCount,
        matchTotal: layout.matchTotal,
        visible: layout.visibleCount,
        matchLabel: describeQuery(state.search, state.entities, entities),
      }
    : null

  return (
    <main className="page">
      <p className="breadcrumb">
        <Link to={{ pathname: '/discussions', search: location.search }}>
          ← All discussions
        </Link>
      </p>

      <PageHeader
        description={
          thread
            ? 'Where in this discussion each model comes up — block height is post length, indent is reply depth.'
            : 'Pick a thread to map its discussion.'
        }
        isFetching={threadQuery.isFetching && !threadQuery.isPending}
        title={thread?.title ?? 'Discussion map'}
      />

      <MapToolbar
        entities={entities}
        onClear={clearFilters}
        onDepth={(value) =>
          patchView({ depth: value === 'auto' ? null : value })
        }
        onHideQuiet={(value) => patchView({ hideQuiet: value })}
        onSearch={(value) => patchQuery({ search: value })}
        onToggleEntity={toggleEntity}
        state={state}
        summary={summary}
      />

      {threadQuery.isError ? (
        <ErrorState
          error={threadQuery.error}
          onRetry={() => void threadQuery.refetch()}
        />
      ) : null}

      <div className="map-layout">
        <DiscussionRail onSelect={selectThread} selectedId={state.thread} />

        <div className="map-pane-wrap">
          {state.thread === null ? (
            <p className="state-message" role="status">
              <strong>No thread selected.</strong>
              <span>Choose one from the list to draw its discussion map.</span>
            </p>
          ) : null}

          {threadQuery.isPending && state.thread !== null ? (
            <LoadingState label="Loading the discussion" />
          ) : null}

          {thread ? (
            <DiscussionMap
              activeId={activeId}
              layout={layout}
              onFocus={(id) => focusComment(id)}
              onGeometry={(width) => handleGeometry(width)}
              onToggle={handleToggle}
            />
          ) : null}
        </div>

        {thread ? (
          <DiscussionReader
            collapsed={collapsed}
            focusId={focusId}
            onClearFocus={() => focusComment(null)}
            onReadingChange={setReadingId}
            onToggle={handleToggle}
            readingId={readingId}
            search={state.search}
            staleFocus={
              state.comment !== null && focusId === null ? state.comment : null
            }
            thread={thread}
            tree={tree}
          />
        ) : (
          <section className="reader" aria-label="Reader">
            <div className="reader__scroll">
              <p className="state-message" role="status">
                <strong>Nothing to read yet.</strong>
                <span>
                  The reader shows the thread you pick, scoped to whichever block
                  you select.
                </span>
              </p>
            </div>
          </section>
        )}
      </div>
    </main>
  )
}

/**
 * What the match count is counting, in words.
 *
 * The toolbar's line is the honest counterweight to the map: it says how many
 * comments matched, how many rows are drawn, and *what* was matched — so a filter
 * that produces almost nothing reads as "narrow question" rather than "broken
 * page".
 */
function describeQuery(
  search: string,
  active: readonly string[],
  vocabulary: readonly { slug: string; label: string }[],
): string | null {
  const labels = active.map(
    (slug) => vocabulary.find((entity) => entity.slug === slug)?.label ?? slug,
  )

  if (labels.length === 1 && search === '') return labels[0]
  if (labels.length > 0 && search !== '') {
    return `${labels.length === 1 ? labels[0] : `${labels.length} filters`} + search`
  }
  if (labels.length > 1) return `${labels.length} filters`
  if (search !== '') return 'your search'
  return null
}
