import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { getCategory, type Category } from '../../api'
import { formatNumber } from '../../app/format'
import { useGlobalFilters } from '../../app/useGlobalFilters'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'

const categoryNames: Record<Category, string> = {
  agent: 'Agent',
  document: 'Document',
  search: 'Search',
  webdev: 'WebDev',
}

export function CategoriesPage() {
  const { filters, clearFilters } = useGlobalFilters()
  const category: Category = filters.category === 'all' ? 'agent' : filters.category
  const query = useQuery({
    queryKey: ['category', category, filters.search, filters.provider],
    queryFn: ({ signal }) =>
      getCategory(
        category,
        {
          search: filters.search,
          organization: filters.provider,
          ordering: ['rank'],
          pageSize: 50,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
  })

  return (
    <main className="page">
      <PageHeader
        count={query.data?.count}
        description={`${categoryNames[category]} results from LMArena's retained agent model set.`}
        isFetching={query.isFetching && !query.isPending}
        title={`${categoryNames[category]} leaderboard`}
      />

      {query.isPending ? <LoadingState label={`Loading ${category} leaderboard`} /> : null}
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
                <th scope="col">{query.data.meta.metric_kind ?? 'Metric'}</th>
                <th scope="col">Samples</th>
                <th scope="col">Published</th>
              </tr>
            </thead>
            <tbody>
              {query.data.results.map((row) => (
                <tr key={row.model.key}>
                  <td className="numeric-cell">{row.category.rank ?? 'N/A'}</td>
                  <th scope="row">{row.model.name}</th>
                  <td>{row.model.organization ?? 'Unknown'}</td>
                  <td className="numeric-cell">
                    {formatNumber(row.category.metric_value, 3)}
                  </td>
                  <td className="numeric-cell">
                    {row.category.sample_size?.toLocaleString() ?? 'Not reported'}
                  </td>
                  <td>{row.category.leaderboard_publish_date ?? 'Not reported'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </main>
  )
}
