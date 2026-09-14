import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowUpRight } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

import { getOverview, type Category, type OverviewRow } from '../../api'
import { formatCurrency, formatNumber } from '../../app/format'
import { useGlobalFilters } from '../../app/useGlobalFilters'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'

const categoryLabels: Record<Category, string> = {
  agent: 'Agent score',
  document: 'Document rating',
  search: 'Search rating',
  webdev: 'WebDev rating',
}

function selectedMetric(row: OverviewRow, category: Category | 'all') {
  return row.categories[category === 'all' ? 'agent' : category]
}

export function OverviewPage() {
  const location = useLocation()
  const { filters, clearFilters } = useGlobalFilters()
  const includedCategories =
    filters.category === 'all' || filters.category === 'agent'
      ? 'all'
      : [filters.category]
  const query = useQuery({
    queryKey: ['overview', filters],
    queryFn: ({ signal }) =>
      getOverview(
        {
          search: filters.search,
          organization: filters.provider,
          includeCategories: includedCategories,
          ordering: ['rank'],
          pageSize: 50,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
  })
  const metricLabel = categoryLabels[
    filters.category === 'all' ? 'agent' : filters.category
  ]

  return (
    <main className="page">
      <PageHeader
        count={query.data?.count}
        description="Models with complete LMArena and Artificial Analysis coverage."
        isFetching={query.isFetching && !query.isPending}
        title="Model overview"
      />

      {query.isPending ? <LoadingState label="Loading model overview" /> : null}
      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {query.data?.results.length === 0 ? <EmptyState onClear={clearFilters} /> : null}

      {query.data && query.data.results.length > 0 ? (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Model</th>
                <th scope="col">Provider</th>
                <th scope="col">{metricLabel}</th>
                <th scope="col">AA intelligence</th>
                <th scope="col">Cost / task</th>
                <th aria-label="Open model" scope="col" />
              </tr>
            </thead>
            <tbody>
              {query.data.results.map((row) => {
                const metric = selectedMetric(row, filters.category)
                return (
                  <tr key={row.model.key}>
                    <td className="numeric-cell">{row.categories.agent.rank ?? 'N/A'}</td>
                    <th scope="row">{row.model.name}</th>
                    <td>{row.model.organization ?? 'Unknown'}</td>
                    <td className="numeric-cell">
                      {metric ? formatNumber(metric.metric_value, 3) : 'Not evaluated'}
                    </td>
                    <td className="numeric-cell">
                      {formatNumber(row.aa.intelligence_index)}
                    </td>
                    <td className="numeric-cell">
                      {formatCurrency(row.aa.cost_per_task, 4)}
                    </td>
                    <td className="action-cell">
                      <Link
                        aria-label={`Open ${row.model.name}`}
                        className="icon-link"
                        title={`Open ${row.model.name}`}
                        to={{
                          pathname: `/models/${encodeURIComponent(row.model.key)}`,
                          search: location.search,
                        }}
                      >
                        <ArrowUpRight aria-hidden="true" size={17} />
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </main>
  )
}
