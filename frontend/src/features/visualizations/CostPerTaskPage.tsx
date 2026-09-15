import { useCallback, useMemo, useState } from 'react'
import { ArrowLeft, ArrowUpRight } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { formatCurrency } from '../../app/format'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'
import { CostPerTaskChart } from './CostPerTaskChart'
import {
  COST_SEGMENT_META,
  type CostBar,
  type CostSegmentId,
} from './costBars'
import { useOverviewCostBars } from './useOverviewScatter'

const LEGEND_SEGMENTS = ['input', 'output', 'cacheWrite', 'cacheHit'] as const

export function CostPerTaskPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const query = useOverviewCostBars()
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const [pinnedSegment, setPinnedSegment] = useState<CostSegmentId | null>(null)
  const [legendHover, setLegendHover] = useState<CostSegmentId | null>(null)
  const focusSegment = pinnedSegment ?? legendHover
  const model = query.data
  const hovered = model?.bars.find((bar) => bar.key === hoverKey) ?? null
  const cheapest = useMemo(() => model?.bars.slice(0, 6) ?? [], [model])

  const onSelect = useCallback(
    (key: string) => {
      navigate({
        pathname: `/models/${encodeURIComponent(key)}`,
        search: location.search,
      })
    },
    [location.search, navigate],
  )

  const toggleSegment = (id: CostSegmentId) => {
    setPinnedSegment((current) => (current === id ? null : id))
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
        count={model?.bars.length}
        description="Weighted USD cost per Intelligence Index task. Each bar is split in proportion to the model's list prices for input, output, and cache tokens."
        isFetching={query.isFetching && !query.isPending}
        title="Cost per task"
      />

      {query.isPending ? <LoadingState label="Loading cost per task" rows={5} /> : null}
      {query.isError && !model ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {model && model.bars.length === 0 ? (
        <EmptyState message="No complete models currently have a measured cost per task." />
      ) : null}

      {model && model.bars.length > 0 ? (
        <>
          <div className="pareto-legend" aria-label="Chart legend">
            {LEGEND_SEGMENTS.map((id) => (
              <button
                aria-pressed={pinnedSegment === id}
                className={`pareto-legend__item pareto-legend__item--provider${pinnedSegment === id ? ' is-pinned' : ''}`}
                key={id}
                onClick={() => toggleSegment(id)}
                onPointerEnter={() => setLegendHover(id)}
                onPointerLeave={() => setLegendHover(null)}
                type="button"
              >
                <span
                  className="pareto-legend__swatch"
                  style={{ background: `var(${COST_SEGMENT_META[id].token})` }}
                />
                {COST_SEGMENT_META[id].label}
              </button>
            ))}
          </div>

          <div className="pareto-layout">
            <figure className="pareto-figure">
              <div className="pareto-chart-frame">
                <CostPerTaskChart
                  hoverKey={hoverKey}
                  model={model}
                  onHover={setHoverKey}
                  onSelect={onSelect}
                  pinnedSegment={focusSegment}
                  variant="interactive"
                />
              </div>
              <figcaption>
                Source: Artificial Analysis cost per Intelligence Index task, joined to
                LMArena. Stacks are a list-price mix, not Artificial Analysis's unpublished
                usage-weighted token split. Null prices are omitted from the mix, never
                treated as zero.
                {model.omitted > 0
                  ? ` ${model.omitted} model${model.omitted === 1 ? '' : 's'} omitted.`
                  : ''}
              </figcaption>
            </figure>

            <aside className="pareto-aside">
              <Inspector
                medianCost={model.medianCost}
                point={hovered}
                search={location.search}
              />
              <section aria-labelledby="cost-cheapest-heading">
                <h2 id="cost-cheapest-heading">Cheapest tasks</h2>
                <ol className="pareto-front-list">
                  {cheapest.map((bar) => (
                    <li key={bar.key}>
                      <Link
                        className={`pareto-front-link${hoverKey === bar.key ? ' is-active' : ''}`}
                        onBlur={() => setHoverKey(null)}
                        onFocus={() => setHoverKey(bar.key)}
                        onPointerEnter={() => setHoverKey(bar.key)}
                        onPointerLeave={() => setHoverKey(null)}
                        to={{
                          pathname: `/models/${encodeURIComponent(bar.key)}`,
                          search: location.search,
                        }}
                      >
                        <span>{bar.name}</span>
                        <small>{formatCurrency(bar.cost, 4)}</small>
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
  search,
}: {
  point: CostBar | null
  medianCost: number
  search: string
}) {
  if (!point) {
    return (
      <section className="pareto-inspector" aria-live="polite">
        <p className="pareto-inspector__kicker">Explore</p>
        <h2>Hover a model</h2>
        <p>
          Bar height is the measured cost per Intelligence Index task. The median is{' '}
          {formatCurrency(medianCost, 2)}. Hover a bar to see how list prices split that
          total. Click to open the model card.
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
          <dt>Cost / task</dt>
          <dd>{formatCurrency(point.cost, 4)}</dd>
        </div>
        {point.segments.map((segment) => (
          <div key={segment.id}>
            <dt>{segment.label}</dt>
            <dd>
              {formatCurrency(segment.value, 4)}
              {segment.price === null
                ? ''
                : ` · ${formatCurrency(segment.price, 2)}/1M`}
            </dd>
          </div>
        ))}
      </dl>
      <p className="pareto-inspector__flags">
        {point.cost < medianCost
          ? 'Cheaper than the median task.'
          : point.cost > medianCost
            ? 'More expensive than the median task.'
            : 'At the median task cost.'}
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
