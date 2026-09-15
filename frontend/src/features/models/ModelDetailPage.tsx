import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { Link, useLocation, useParams } from 'react-router-dom'

import { getModel } from '../../api'
import { formatCurrency, formatNumber } from '../../app/format'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'

export function ModelDetailPage() {
  const { key = '' } = useParams()
  const location = useLocation()
  const query = useQuery({
    queryKey: ['model', key],
    queryFn: ({ signal }) => getModel(key, { signal }),
    enabled: key !== '',
  })

  return (
    <main className="page model-detail">
      <Link className="back-link" to={{ pathname: '/models', search: location.search }}>
        <ArrowLeft aria-hidden="true" size={16} />
        All models
      </Link>

      {query.isPending ? <LoadingState label="Loading model details" rows={5} /> : null}
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : null}

      {query.data ? (
        <>
          <header className="model-detail__header">
            <p>{query.data.model.organization ?? 'Unknown provider'}</p>
            <h1>{query.data.model.name}</h1>
            <span>{query.data.model.license ?? 'License not reported'}</span>
          </header>

          <section className="stat-strip" aria-label="Model summary">
            <div className="stat-item">
              <span>Agent rank</span>
              <strong>{query.data.categories.agent.rank ?? 'N/A'}</strong>
            </div>
            <div className="stat-item">
              <span>AA intelligence</span>
              <strong>{formatNumber(query.data.aa.intelligence_index)}</strong>
            </div>
            <div className="stat-item">
              <span>Cost / task</span>
              <strong>{formatCurrency(query.data.aa.cost_per_task, 4)}</strong>
            </div>
            <div className="stat-item">
              <span>Output speed</span>
              <strong>
                {query.data.aa.performance.median_output_tokens_per_second === null
                  ? 'Not measured'
                  : `${formatNumber(query.data.aa.performance.median_output_tokens_per_second)} tok/s`}
              </strong>
            </div>
          </section>

          <section className="category-summary" aria-labelledby="category-summary-title">
            <h2 id="category-summary-title">Category coverage</h2>
            <div className="category-summary__grid">
              {Object.entries(query.data.categories).map(([category, block]) => (
                <article className="category-summary__item" key={category}>
                  <h3>{category}</h3>
                  <strong>{block ? formatNumber(block.metric_value, 3) : 'Not evaluated'}</strong>
                  <span>{block?.rank ? `Rank ${block.rank}` : 'No published rank'}</span>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </main>
  )
}
