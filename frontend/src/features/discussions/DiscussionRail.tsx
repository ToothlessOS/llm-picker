import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, MessageSquare } from 'lucide-react'

import { getDiscussions, type DiscussionThreadRow } from '../../api'
import { formatNumber, formatRelativeTime } from '../../app/format'
import { useDiscussionFilters } from '../../app/useDiscussionFilters'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'

const RAIL_PAGE_SIZE = 20

export interface DiscussionRailProps {
  selectedId: number | null
  onSelect: (hnId: number) => void
}

/**
 * The thread column — ConVis's topic list, with *threads* as the topics.
 *
 * It reads the same `q` and `entity` params the toolbar writes, through the same
 * hook the thread-list page uses, so a search narrows the rail and the table
 * identically. Its own `page` param is separate from the map's state: paging
 * through threads is not a change to what the map is showing.
 */
export function DiscussionRail({ selectedId, onSelect }: DiscussionRailProps) {
  const { filters, updateFilters } = useDiscussionFilters()

  const query = useQuery({
    queryKey: ['discussions', 'rail', filters],
    queryFn: ({ signal }) =>
      getDiscussions(
        {
          search: filters.search,
          entity: filters.entities.length > 0 ? filters.entities : undefined,
          ordering: [filters.ordering],
          page: filters.page,
          pageSize: RAIL_PAGE_SIZE,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
    staleTime: 300_000,
    refetchInterval: 300_000,
  })

  const pageCount = query.data
    ? Math.max(1, Math.ceil(query.data.count / RAIL_PAGE_SIZE))
    : 1

  return (
    <section className="rail" aria-label="Threads">
      <p className="rail__heading">
        Threads
        {query.data ? (
          <span className="muted">{formatNumber(query.data.count, 0)}</span>
        ) : null}
      </p>

      {query.isPending ? <LoadingState label="Loading threads" /> : null}
      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : null}

      {query.data ? (
        <>
          <ol className="rail__list">
            {query.data.results.map((row) => (
              <RailRow
                isSelected={row.hn_id === selectedId}
                key={row.hn_id}
                onSelect={onSelect}
                row={row}
              />
            ))}
          </ol>

          {query.data.results.length === 0 ? (
            <p className="state-message" role="status">
              <strong>No threads match.</strong>
              <span>Clear the search and filters to see the whole bank.</span>
            </p>
          ) : null}

          {pageCount > 1 ? (
            <RailPager
              count={query.data.count}
              onPage={(page) => updateFilters({ page })}
              page={filters.page}
              pageCount={pageCount}
            />
          ) : null}
        </>
      ) : null}
    </section>
  )
}

/**
 * The rail's pager.
 *
 * A plain link-free pair of buttons writing `?page=`, because the rail is a
 * browsable list and the "load more" idiom would grow the column past the pane.
 */
function RailPager({
  page,
  pageCount,
  count,
  onPage,
}: {
  page: number
  pageCount: number
  count: number
  onPage: (page: number) => void
}) {
  return (
    <div className="rail__pager">
      <button
        aria-label="Previous page of threads"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        type="button"
      >
        <ChevronLeft aria-hidden="true" size={16} />
      </button>
      <span className="muted">
        {page} / {formatNumber(pageCount, 0)} · {formatNumber(count, 0)} threads
      </span>
      <button
        aria-label="Next page of threads"
        disabled={page >= pageCount}
        onClick={() => onPage(page + 1)}
        type="button"
      >
        <ChevronRight aria-hidden="true" size={16} />
      </button>
    </div>
  )
}

function RailRow({
  row,
  isSelected,
  onSelect,
}: {
  row: DiscussionThreadRow
  isSelected: boolean
  onSelect: (hnId: number) => void
}) {
  return (
    <li>
      <button
        aria-current={isSelected ? 'true' : undefined}
        className={`rail__row${isSelected ? ' is-selected' : ''}`}
        onClick={() => onSelect(row.hn_id)}
        type="button"
      >
        <span className="rail__title">{row.title}</span>
        <span className="rail__meta">
          <MessageSquare aria-hidden="true" size={13} />
          {row.comments_stored > 0
            ? formatNumber(row.comments_stored, 0)
            : 'pending'}
          {row.points !== null ? (
            <span className="muted">
              · {formatNumber(row.points, 0)} points
            </span>
          ) : null}
          <span className="muted">· {formatRelativeTime(row.posted_at)}</span>
        </span>
        {row.entities.length > 0 ? (
          <span className="rail__entities">
            {row.entities.slice(0, 4).map((entity) => (
              <span className="rail__entity" key={entity.slug}>
                {entity.label}
              </span>
            ))}
          </span>
        ) : null}
      </button>
    </li>
  )
}
