import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import type { DiscussionOrderingField, Ordering } from '../api'

export interface DiscussionFilters {
  search: string
  /**
   * Entity slugs, OR-ed together by the endpoint — which is the correct
   * semantics, because the endpoint's own filter is
   * `slug__in | vendor__slug__in` with the vendor roll-up included.
   *
   * An **array**, and that is a correctness requirement rather than a
   * convenience. The endpoint validates every slug against the live vocabulary
   * and answers `400` for an unknown one, so a comma-joined list sent as a single
   * element is an error state, not an empty result. The map writes multi-entity
   * URLs, so this has to read them the same way.
   */
  entities: string[]
  ordering: Ordering<DiscussionOrderingField>
  page: number
}

export const DISCUSSION_DEFAULT_ORDERING: Ordering<DiscussionOrderingField> =
  '-rank_score'

/**
 * How many entity filters may be active at once.
 *
 * A UI policy, not a backend one — the endpoint accepts any number. It exists so
 * the map's colour story stays legible: every active filter is meant to be
 * tellable apart at a glance, and past a handful of hues that stops being true.
 */
export const MAX_DISCUSSION_FILTERS = 6

/**
 * The `entity` param as a list.
 *
 * Exported because the map reads and writes the *same* param — a filter set on
 * one page has to mean the same thing on the other, and two parsers is how those
 * drift apart.
 */
export function parseEntityList(raw: string | null): string[] {
  if (raw === null) return []
  return raw
    .split(',')
    .map((slug) => slug.trim())
    .filter((slug) => slug !== '')
}

/**
 * Discussion filter state, kept in the URL.
 *
 * The same convention as `useGlobalFilters` — filters live in the search params so
 * a filtered view is linkable and the back button works — but with its own param
 * names, and that is deliberate: the global `provider` key means a *LMArena
 * organization string* (`"Anthropic"`) on `/models`, and would mean an *entity
 * slug* (`"anthropic"`) here. One key carrying two vocabularies is a
 * wrong-filter bug that presents as an empty result.
 *
 * `q` is shared with the global filters, because "keyword search" is genuinely the
 * same job on both pages.
 */
export function useDiscussionFilters() {
  const [searchParams, setSearchParams] = useSearchParams()

  const filters = useMemo<DiscussionFilters>(() => {
    const page = Number.parseInt(searchParams.get('page') ?? '', 10)
    const ordering = searchParams.get('ordering')?.trim()
    return {
      search: searchParams.get('q')?.trim() ?? '',
      entities: parseEntityList(searchParams.get('entity')),
      ordering: (ordering || DISCUSSION_DEFAULT_ORDERING) as Ordering<DiscussionOrderingField>,
      page: Number.isFinite(page) && page > 0 ? page : 1,
    }
  }, [searchParams])

  const updateFilters = useCallback(
    (patch: Partial<DiscussionFilters>) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)
          const values: DiscussionFilters = { ...filters, ...patch }

          if (values.search) next.set('q', values.search)
          else next.delete('q')

          if (values.entities.length > 0) {
            next.set('entity', values.entities.join(','))
          } else {
            next.delete('entity')
          }

          if (values.ordering !== DISCUSSION_DEFAULT_ORDERING) {
            next.set('ordering', values.ordering)
          } else {
            next.delete('ordering')
          }

          if (values.page > 1) next.set('page', String(values.page))
          else next.delete('page')

          return next
        },
        // `replace` rather than push: typing in the search box would otherwise
        // leave one history entry per keystroke, and "back" would have to be
        // pressed a dozen times to leave the page.
        { replace: true },
      )
    },
    [filters, setSearchParams],
  )

  /** Changing *what* you are looking at returns you to page one. */
  const patchAndReset = useCallback(
    (patch: Partial<DiscussionFilters>) => updateFilters({ ...patch, page: 1 }),
    [updateFilters],
  )

  const clearFilters = useCallback(() => {
    setSearchParams({}, { replace: true })
  }, [setSearchParams])

  return {
    filters,
    updateFilters,
    patchAndReset,
    clearFilters,
    hasActiveFilters:
      filters.search !== '' ||
      filters.entities.length > 0 ||
      filters.ordering !== DISCUSSION_DEFAULT_ORDERING,
  }
}

export const DISCUSSION_ORDERING_OPTIONS: ReadonlyArray<{
  value: Ordering<DiscussionOrderingField>
  label: string
}> = [
  { value: '-rank_score', label: 'Score (points + comments)' },
  { value: '-points', label: 'Most points' },
  { value: '-num_comments', label: 'Most comments' },
  { value: '-posted_at', label: 'Newest first' },
]
