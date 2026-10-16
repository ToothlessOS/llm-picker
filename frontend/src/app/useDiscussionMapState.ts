import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import type { DepthMode } from '../features/discussions/discussionTree'
import { MAX_DISCUSSION_FILTERS, parseEntityList } from './useDiscussionFilters'

export interface DiscussionMapState {
  /** The thread being mapped. `null` until one is chosen. */
  thread: number | null
  /** The focused comment, as an `hn_id` or a `path`. `null` is the whole thread. */
  comment: string | null
  search: string
  entities: string[]
  /** `null` means "decide from the thread's size" — see `defaultDepthMode`. */
  depth: DepthMode | null
  hideQuiet: boolean
}

export const DEPTH_OPTIONS: ReadonlyArray<{ value: DepthMode | 'auto'; label: string }> = [
  { value: 'auto', label: 'Auto (by thread size)' },
  { value: 'roots', label: 'Top level only' },
  { value: 'layer1', label: 'First layer of replies' },
  { value: 'all', label: 'Every reply' },
]

const DEPTH_MODES: readonly DepthMode[] = ['roots', 'layer1', 'all']

function parseThread(raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw.trim())) return null
  const id = Number.parseInt(raw.trim(), 10)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

function parseDepth(raw: string | null): DepthMode | null {
  return DEPTH_MODES.find((mode) => mode === raw?.trim()) ?? null
}

/**
 * The map's view state, kept in the URL.
 *
 * Every param is here rather than in component state so a map is linkable: the
 * thread, the focused comment, the search, the filters and the depth all travel
 * together, which is what makes "here is the part of this thread where people
 * discuss Qwen" a thing you can send someone.
 *
 * **Two write modes, and the split is the point.** `thread` and `comment` push a
 * history entry, because they are *navigation* — Back should undo a focus the way
 * it undoes anything else. Everything else replaces, matching
 * `useDiscussionFilters`: one history entry per keystroke in a search box is the
 * bug that convention exists to prevent.
 *
 * `q` and `entity` are the same keys the thread list uses, deliberately. A search
 * means the same thing on both pages — it narrows the rail on the map and it
 * filters the table on the list.
 */
export function useDiscussionMapState() {
  const [searchParams, setSearchParams] = useSearchParams()

  const state = useMemo<DiscussionMapState>(
    () => ({
      thread: parseThread(searchParams.get('thread')),
      comment: searchParams.get('comment')?.trim() || null,
      search: searchParams.get('q')?.trim() ?? '',
      entities: parseEntityList(searchParams.get('entity')),
      depth: parseDepth(searchParams.get('depth')),
      hideQuiet: searchParams.get('hidequiet') === '1',
    }),
    [searchParams],
  )

  /** Choose a thread. Selecting one always clears the focus — it belonged to another thread. */
  const selectThread = useCallback(
    (hnId: number) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)
          next.set('thread', String(hnId))
          next.delete('comment')
          return next
        },
        { replace: false },
      )
    },
    [setSearchParams],
  )

  const focusComment = useCallback(
    (ref: string | number | null) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)
          if (ref === null || String(ref).trim() === '') next.delete('comment')
          else next.set('comment', String(ref))
          return next
        },
        { replace: false },
      )
    },
    [setSearchParams],
  )

  /**
   * Change *what is being looked at*.
   *
   * A search or filter change drops the focus, because a focus the new query has
   * nothing to say about leaves the reader scoped to a subtree with nothing in
   * it. Depth and the quiet-branch toggle do **not**, because they change how
   * much is drawn rather than what was asked for — losing your place for reaching
   * for more context would be a bug, not a feature.
   */
  const patchQuery = useCallback(
    (patch: Partial<Pick<DiscussionMapState, 'search' | 'entities'>>) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)

          if (patch.search !== undefined) {
            if (patch.search.trim()) next.set('q', patch.search.trim())
            else next.delete('q')
          }

          if (patch.entities !== undefined) {
            if (patch.entities.length > 0) next.set('entity', patch.entities.join(','))
            else next.delete('entity')
          }

          next.delete('comment')
          // The rail paginates over the *same* `q` and `entity`, so a narrower
          // question has to start at its own page one — otherwise searching from
          // page five of the bank lands on an empty page of a much shorter list.
          next.delete('page')
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  /** Change how much is drawn. Keeps the focus. */
  const patchView = useCallback(
    (patch: { depth?: DepthMode | null; hideQuiet?: boolean }) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)

          if (patch.depth !== undefined) {
            if (patch.depth === null) next.delete('depth')
            else next.set('depth', patch.depth)
          }

          if (patch.hideQuiet !== undefined) {
            if (patch.hideQuiet) next.set('hidequiet', '1')
            else next.delete('hidequiet')
          }

          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  /** Add or remove one entity filter, refusing to exceed the palette's reach. */
  const toggleEntity = useCallback(
    (slug: string) => {
      const active = state.entities
      if (active.includes(slug)) {
        patchQuery({ entities: active.filter((value) => value !== slug) })
      } else if (active.length < MAX_DISCUSSION_FILTERS) {
        patchQuery({ entities: [...active, slug] })
      }
    },
    [patchQuery, state.entities],
  )

  const clearFilters = useCallback(() => {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current)
        for (const key of ['q', 'entity', 'hidequiet', 'comment']) next.delete(key)
        return next
      },
      { replace: true },
    )
  }, [setSearchParams])

  return {
    state,
    selectThread,
    focusComment,
    patchQuery,
    patchView,
    toggleEntity,
    clearFilters,
    hasActiveFilters: state.search !== '' || state.entities.length > 0,
  }
}
