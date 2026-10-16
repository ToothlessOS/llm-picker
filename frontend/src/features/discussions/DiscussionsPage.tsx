import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowUpRight, MessageSquare, Waypoints } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

import {
  getDiscussions,
  type DiscussionOrderingField,
  type DiscussionThreadRow,
  type Ordering,
} from '../../api'
import {
  DISCUSSION_ORDERING_OPTIONS,
  useDiscussionFilters,
} from '../../app/useDiscussionFilters'
import { formatNumber, formatRelativeTime } from '../../app/format'
import { PageHeader } from '../../components/PageHeader'
import { SearchField } from '../../components/SearchField'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'

function EntityChips({ entities }: { entities: DiscussionThreadRow['entities'] }) {
  if (entities.length === 0) return <span className="muted">—</span>
  return (
    <span className="entity-chips">
      {entities.map((entity) => (
        <span
          className={`entity-chip entity-chip--${entity.kind}`}
          key={entity.slug}
          title={`${entity.matched_text} · ${entity.mentions} mention(s)`}
        >
          {entity.label}
        </span>
      ))}
    </span>
  )
}

/**
 * How much of a discussion we actually hold.
 *
 * The two numbers together whenever they differ, because either alone misleads:
 * `num_comments` is what Hacker News reports and `comments_stored` is what we
 * kept. Three states, and they mean different things:
 *
 * * **`pending`** — the tree has not been fetched yet. Deliberately not `0`, which
 *   would say "nobody commented" when the truth is "we have not looked".
 * * **`600 / 1,216`** — we hold part of it. Either the ingest cap truncated the
 *   tree, or the thread has gained comments since we last fetched it; the tooltip
 *   says which, since only the first is permanent.
 * * **`600`** — we hold all of it.
 *
 * The rule is "show the reported total when it differs", not "show it when
 * truncated", which is also what the thread page does — so the same thread reads
 * the same way in both places.
 */
function CommentCount({ row }: { row: DiscussionThreadRow }) {
  if (row.comments_stored === 0) {
    return (
      <span className="muted" title="The comment tree has not been fetched yet">
        pending
      </span>
    )
  }

  const stored = formatNumber(row.comments_stored, 0)
  const behind = row.num_comments !== null && row.num_comments !== row.comments_stored
  if (!behind) return <span>{stored}</span>

  const reason = row.tree_truncated
    ? `Truncated by the ingest cap — ${stored} of ${formatNumber(row.num_comments, 0)} kept`
    : `Hacker News now reports more comments than we last fetched; the next refresh will pick them up`

  return (
    <span title={reason}>
      {stored}
      <span className="muted"> / {formatNumber(row.num_comments, 0)}</span>
    </span>
  )
}

export function DiscussionsPage() {
  const location = useLocation()
  const { filters, patchAndReset, clearFilters, hasActiveFilters } =
    useDiscussionFilters()

  const query = useQuery({
    queryKey: ['discussions', filters],
    queryFn: ({ signal }) =>
      getDiscussions(
        {
          search: filters.search,
          entity: filters.entities.length > 0 ? filters.entities : undefined,
          ordering: [filters.ordering],
          page: filters.page,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
    // The bank is rebuilt hourly, so polling faster than that only spends requests.
    staleTime: 300_000,
    refetchInterval: 300_000,
  })

  const freshness = query.data?.meta.discussions

  return (
    <main className="page">
      <PageHeader
        count={query.data?.count}
        description={
          freshness
            ? `LLM-related threads from Hacker News, retained for ${freshness.window_days} days.`
            : 'LLM-related threads from Hacker News.'
        }
        isFetching={query.isFetching && !query.isPending}
        title="Discussions"
      />

      <div className="filter-band filter-band--inline" aria-label="Discussion search">
        <div className="filter-band__inner">
          <SearchField
            label="Search discussions"
            onSearchChange={(search) => patchAndReset({ search })}
            placeholder="Title or comment text"
            value={filters.search}
          />
          <label className="filter-control">
            <span className="filter-control__label">Order</span>
            <select
              onChange={(event) =>
                // A DOM event hands back a string; the options above are the
                // only values this select can produce.
                patchAndReset({
                  ordering: event.target.value as Ordering<DiscussionOrderingField>,
                })
              }
              value={filters.ordering}
            >
              {DISCUSSION_ORDERING_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {query.isPending ? <LoadingState label="Loading discussions" /> : null}
      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {query.data?.results.length === 0 ? (
        <EmptyState
          message={
            hasActiveFilters
              ? 'No discussion matches the current filters.'
              : 'No discussions have been collected yet. The hourly job will fill this in.'
          }
          onClear={hasActiveFilters ? clearFilters : undefined}
          title={hasActiveFilters ? 'No matching discussions' : 'No discussions yet'}
        />
      ) : null}

      {query.data && query.data.results.length > 0 ? (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Thread</th>
                <th scope="col">Provider / service</th>
                <th className="numeric-cell" scope="col">
                  Points
                </th>
                <th className="numeric-cell" scope="col">
                  Comments
                </th>
                <th scope="col">Posted</th>
                <th aria-label="Open thread" scope="col" />
              </tr>
            </thead>
            <tbody>
              {query.data.results.map((row) => (
                <tr key={row.hn_id}>
                  <th scope="row">
                    <Link
                      className="table-link"
                      to={{
                        pathname: `/discussions/${row.hn_id}`,
                        search: location.search,
                      }}
                    >
                      {row.title}
                    </Link>
                    {row.domain ? (
                      <span className="table-subtitle">{row.domain}</span>
                    ) : null}
                  </th>
                  <td>
                    <EntityChips entities={row.entities} />
                  </td>
                  <td className="numeric-cell">{formatNumber(row.points, 0)}</td>
                  <td className="numeric-cell">
                    <CommentCount row={row} />
                  </td>
                  <td>{formatRelativeTime(row.posted_at)}</td>
                  <td className="action-cell">
                    <Link
                      aria-label={`Open the discussion map for "${row.title}"`}
                      className="icon-link"
                      to={{
                        pathname: '/discussions/map',
                        search: `?thread=${row.hn_id}`,
                      }}
                    >
                      <Waypoints aria-hidden="true" size={16} />
                    </Link>
                    <a
                      aria-label={`Open "${row.title}" on Hacker News`}
                      className="table-link"
                      href={row.hn_url}
                      rel="noreferrer"
                      target="_blank"
                    >
                      <ArrowUpRight aria-hidden="true" size={16} />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {freshness ? (
        <p className="page-note">
          <MessageSquare aria-hidden="true" size={15} />
          {formatNumber(freshness.counts.threads, 0)} threads ·{' '}
          {formatNumber(freshness.counts.comments, 0)} comments ·{' '}
          {formatNumber(freshness.counts.tags, 0)} entity tags
          {freshness.last_success_at
            ? ` · last refreshed ${formatRelativeTime(freshness.last_success_at)}`
            : ' · awaiting the first refresh'}
        </p>
      ) : null}
    </main>
  )
}
