import { useCallback, useMemo, useState } from 'react'
import { ArrowLeft, ArrowUpRight } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { formatCurrency, formatNumber } from '../../app/format'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'
import { PerformanceVsCostChart } from './PerformanceVsCostChart'
import {
  providerColor,
  type ScatterPoint,
} from './scatter'
import { useOverviewScatter } from './useOverviewScatter'

export function PerformanceVsCostPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const query = useOverviewScatter()
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const [pinnedProvider, setPinnedProvider] = useState<string | null>(null)
  const [legendHover, setLegendHover] = useState<string | null>(null)
  const focusProvider = pinnedProvider ?? legendHover
  const model = query.data
  const hovered = model?.points.find((point) => point.key === hoverKey) ?? null
  const providers = useMemo(() => {
    if (!model) return []
    return [...new Set(model.points.map((point) => point.providerKey))].sort((left, right) =>
      left.localeCompare(right),
    )
  }, [model])

  const onSelect = useCallback(
    (key: string) => {
      navigate({
        pathname: `/models/${encodeURIComponent(key)}`,
        search: location.search,
      })
    },
    [location.search, navigate],
  )

  const toggleProvider = (providerKey: string) => {
    setPinnedProvider((current) => (current === providerKey ? null : providerKey))
  }

  return (
    <main className="page pareto-page">
      <Link
        className="back-link"
        to={{ pathname: '/', search: location.search, hash: 'visualizations' }}
      >
        <ArrowLeft aria-hidden="true" size={16} />
        All charts
      </Link>

      <PageHeader
        count={model?.points.length}
        description="Intelligence versus cost per task. The dashed line is the Pareto front: nothing else plotted is both cheaper and at least as capable."
        isFetching={query.isFetching && !query.isPending}
        title="Performance vs. cost"
      />

      {query.isPending ? <LoadingState label="Loading performance versus cost" rows={5} /> : null}
      {query.isError && !model ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {model && model.points.length === 0 ? (
        <EmptyState message="No complete models currently have both an intelligence index and a measured cost per task." />
      ) : null}

      {model && model.points.length > 0 ? (
        <>
          <div className="pareto-legend" aria-label="Chart legend">
            <span className="pareto-legend__item">
              <span className="pareto-legend__swatch pareto-legend__swatch--quadrant" />
              Most attractive quadrant
            </span>
            <span className="pareto-legend__item">
              <span className="pareto-legend__swatch pareto-legend__swatch--front" />
              Pareto front
            </span>
            {providers.map((providerKey) => {
              const label =
                model.points.find((point) => point.providerKey === providerKey)?.provider ??
                providerKey
              return (
                <button
                  aria-pressed={pinnedProvider === providerKey}
                  className={`pareto-legend__item pareto-legend__item--provider${pinnedProvider === providerKey ? ' is-pinned' : ''}`}
                  key={providerKey}
                  onClick={() => toggleProvider(providerKey)}
                  onPointerEnter={() => setLegendHover(providerKey)}
                  onPointerLeave={() => setLegendHover(null)}
                  type="button"
                >
                  <span
                    className="pareto-legend__swatch"
                    style={{ background: providerColor(providerKey, providers) }}
                  />
                  {label}
                </button>
              )
            })}
          </div>

          <div className="pareto-layout">
            <figure className="pareto-figure">
              <div className="pareto-chart-frame">
                <PerformanceVsCostChart
                  hoverKey={hoverKey}
                  model={model}
                  onHover={setHoverKey}
                  onSelect={onSelect}
                  pinnedProvider={focusProvider}
                  variant="interactive"
                />
              </div>
              <figcaption>
                Source: Artificial Analysis Intelligence Index and weighted USD cost per
                Intelligence Index task, joined to LMArena. Cost is logarithmic. Unmeasured
                costs are omitted, never plotted as zero.
                {model.omitted > 0
                  ? ` ${model.omitted} model${model.omitted === 1 ? '' : 's'} omitted.`
                  : ''}
              </figcaption>
            </figure>

            <aside className="pareto-aside">
              <Inspector
                medianCost={model.medianCost}
                medianIntelligence={model.medianIntelligence}
                point={hovered}
                search={location.search}
              />
              <section aria-labelledby="pareto-front-heading">
                <h2 id="pareto-front-heading">On the front</h2>
                <ol className="pareto-front-list">
                  {model.pareto.map((point) => (
                    <li key={point.key}>
                      <Link
                        className={`pareto-front-link${hoverKey === point.key ? ' is-active' : ''}`}
                        onBlur={() => setHoverKey(null)}
                        onFocus={() => setHoverKey(point.key)}
                        onPointerEnter={() => setHoverKey(point.key)}
                        onPointerLeave={() => setHoverKey(null)}
                        to={{
                          pathname: `/models/${encodeURIComponent(point.key)}`,
                          search: location.search,
                        }}
                      >
                        <span>{point.name}</span>
                        <small>
                          {formatNumber(point.intelligence)} · {formatCurrency(point.cost, 4)}
                        </small>
                      </Link>
                    </li>
                  ))}
                </ol>
              </section>
            </aside>
          </div>
        </>
      ) : null}
    </main>
  )
}

function Inspector({
  point,
  medianCost,
  medianIntelligence,
  search,
}: {
  point: ScatterPoint | null
  medianCost: number
  medianIntelligence: number
  search: string
}) {
  if (!point) {
    return (
      <section className="pareto-inspector" aria-live="polite">
        <p className="pareto-inspector__kicker">Explore</p>
        <h2>Hover a model</h2>
        <p>
          The green region is cheaper than the median ({formatCurrency(medianCost, 2)}) and
          smarter than the median index ({formatNumber(medianIntelligence)}). Click a point to
          open its model card.
        </p>
      </section>
    )
  }

  return (
    <section className="pareto-inspector is-filled" aria-live="polite">
      <p className="pareto-inspector__kicker">{point.provider}</p>
      <h2>{point.name}</h2>
      <dl>
        <div>
          <dt>Intelligence</dt>
          <dd>{formatNumber(point.intelligence)}</dd>
        </div>
        <div>
          <dt>Cost / task</dt>
          <dd>{formatCurrency(point.cost, 4)}</dd>
        </div>
      </dl>
      <p className="pareto-inspector__flags">
        {point.onPareto ? 'On the Pareto front. ' : 'Dominated on this plot. '}
        {point.inAttractiveQuadrant
          ? 'Inside the most attractive quadrant.'
          : 'Outside the most attractive quadrant.'}
      </p>
      <Link
        className="pareto-inspector__link"
        to={{ pathname: `/models/${encodeURIComponent(point.key)}`, search }}
      >
        Open model card
        <ArrowUpRight aria-hidden="true" size={16} />
      </Link>
    </section>
  )
}
