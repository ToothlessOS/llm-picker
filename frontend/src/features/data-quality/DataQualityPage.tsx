import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { getFreshnessState, getMetadata, getUnmatched } from '../../api'
import { formatDateTime } from '../../app/format'
import { useGlobalFilters } from '../../app/useGlobalFilters'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'

export function DataQualityPage() {
  const { filters, clearFilters } = useGlobalFilters()
  const metadataQuery = useQuery({
    queryKey: ['metadata'],
    queryFn: ({ signal }) => getMetadata({ signal }),
    refetchInterval: 60_000,
  })
  const unmatchedQuery = useQuery({
    queryKey: ['unmatched', filters.search, filters.category],
    queryFn: ({ signal }) =>
      getUnmatched(
        {
          search: filters.search,
          category: filters.category === 'all' ? undefined : filters.category,
          current: true,
          pageSize: 25,
        },
        { signal },
      ),
    placeholderData: keepPreviousData,
  })

  if (metadataQuery.isPending) {
    return (
      <main className="page">
        <PageHeader
          description="Source freshness, coverage, and records excluded from joined views."
          title="Data quality"
        />
        <LoadingState label="Loading data quality status" />
      </main>
    )
  }

  if (metadataQuery.isError) {
    return (
      <main className="page">
        <PageHeader
          description="Source freshness, coverage, and records excluded from joined views."
          title="Data quality"
        />
        <ErrorState
          error={metadataQuery.error}
          onRetry={() => void metadataQuery.refetch()}
        />
      </main>
    )
  }

  const metadata = metadataQuery.data

  return (
    <main className="page">
      <PageHeader
        description="Source freshness, coverage, and records excluded from joined views."
        isFetching={metadataQuery.isFetching || unmatchedQuery.isFetching}
        title="Data quality"
      />

      <section className="stat-strip" aria-label="Coverage summary">
        <div className="stat-item">
          <span>Complete models</span>
          <strong>{metadata.counts.complete_agent_entries.toLocaleString()}</strong>
        </div>
        <div className="stat-item">
          <span>LMArena entries</span>
          <strong>{metadata.counts.lmarena_entries.toLocaleString()}</strong>
        </div>
        <div className="stat-item">
          <span>AA models</span>
          <strong>{metadata.counts.aa_models.toLocaleString()}</strong>
        </div>
        <div className="stat-item">
          <span>Current exceptions</span>
          <strong>{metadata.counts.unmatched_records.toLocaleString()}</strong>
        </div>
      </section>

      <section className="source-status-section" aria-labelledby="source-status-title">
        <h2 id="source-status-title">Source status</h2>
        <div className="source-status-grid">
          {Object.entries(metadata.sources).map(([source, freshness]) => (
            <article className="source-status" key={source}>
              <div className="source-status__heading">
                <h3>{source === 'lmarena' ? 'LMArena' : 'Artificial Analysis'}</h3>
                <span className={`status-tag status-tag--${getFreshnessState(freshness)}`}>
                  {getFreshnessState(freshness).replaceAll('_', ' ')}
                </span>
              </div>
              <dl>
                <div>
                  <dt>Last success</dt>
                  <dd>{formatDateTime(freshness.last_success_at)}</dd>
                </div>
                <div>
                  <dt>Last run</dt>
                  <dd>{freshness.last_status ?? 'No runs'}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <section className="exceptions-section" aria-labelledby="exceptions-title">
        <div className="section-heading">
          <div>
            <h2 id="exceptions-title">Current exceptions</h2>
            <p>{unmatchedQuery.data?.count.toLocaleString() ?? 'N/A'} records</p>
          </div>
        </div>

        {unmatchedQuery.isPending ? <LoadingState label="Loading exceptions" rows={4} /> : null}
        {unmatchedQuery.isError && !unmatchedQuery.data ? (
          <ErrorState
            error={unmatchedQuery.error}
            onRetry={() => void unmatchedQuery.refetch()}
          />
        ) : null}
        {unmatchedQuery.data?.results.length === 0 ? (
          <EmptyState
            message="No current data exceptions match these filters."
            onClear={clearFilters}
            title="No matching exceptions"
          />
        ) : null}

        {unmatchedQuery.data && unmatchedQuery.data.results.length > 0 ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col">Source</th>
                  <th scope="col">Category</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Occurrences</th>
                  <th scope="col">Last seen</th>
                </tr>
              </thead>
              <tbody>
                {unmatchedQuery.data.results.map((record) => (
                  <tr key={`${record.source}-${record.category}-${record.reason}-${record.model_key}`}>
                    <th scope="row">{record.model_name ?? record.model_key}</th>
                    <td>{record.source.replace('_', ' ')}</td>
                    <td>{record.category ?? 'N/A'}</td>
                    <td>{record.reason.replaceAll('_', ' ')}</td>
                    <td className="numeric-cell">{record.occurrences.toLocaleString()}</td>
                    <td>{formatDateTime(record.last_seen_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </main>
  )
}
