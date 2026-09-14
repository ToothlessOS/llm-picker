import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { getArtificialAnalysis } from '../../api'
import { formatCurrency, formatNumber } from '../../app/format'
import { useGlobalFilters } from '../../app/useGlobalFilters'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'

export function ArtificialAnalysisPage() {
  const { filters, clearFilters } = useGlobalFilters()
  const query = useQuery({
    queryKey: ['artificial-analysis', filters.search, filters.provider],
    queryFn: ({ signal }) =>
      getArtificialAnalysis(
        {
          search: filters.search,
          creator: filters.provider,
          ordering: ['-intelligence_index'],
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
        description="Artificial Analysis records retained in the LMArena agent set."
        isFetching={query.isFetching && !query.isPending}
        title="AA model catalogue"
      />

      {query.isPending ? <LoadingState label="Loading Artificial Analysis models" /> : null}
      {query.isError && !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {query.data?.results.length === 0 ? <EmptyState onClear={clearFilters} /> : null}

      {query.data && query.data.results.length > 0 ? (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Creator</th>
                <th scope="col">Intelligence</th>
                <th scope="col">Coding</th>
                <th scope="col">Cost / task</th>
                <th scope="col">Output speed</th>
              </tr>
            </thead>
            <tbody>
              {query.data.results.map(({ aa }) => (
                <tr key={aa.id}>
                  <th scope="row">{aa.name}</th>
                  <td>{aa.creator?.name ?? 'Unknown'}</td>
                  <td className="numeric-cell">{formatNumber(aa.intelligence_index)}</td>
                  <td className="numeric-cell">{formatNumber(aa.coding_index)}</td>
                  <td className="numeric-cell">{formatCurrency(aa.cost_per_task, 4)}</td>
                  <td className="numeric-cell">
                    {aa.performance.median_output_tokens_per_second === null
                      ? 'Not measured'
                      : `${formatNumber(aa.performance.median_output_tokens_per_second)} tok/s`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </main>
  )
}
