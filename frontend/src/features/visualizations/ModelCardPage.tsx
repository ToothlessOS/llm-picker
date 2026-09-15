import { useMemo, useState } from 'react'
import { ArrowLeft, ArrowUpRight } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'
import { ModelCardChart } from './ModelCardChart'
import {
  RADAR_AXES,
  RADAR_AXIS_META,
  findCard,
  formatPercentile,
  formatRadarRaw,
  isCompleteCard,
  type ModelCard,
  type RadarAxisId,
} from './modelCard'
import { useOverviewModelCard } from './useOverviewScatter'

export function ModelCardPage() {
  const location = useLocation()
  const query = useOverviewModelCard()
  const catalog = query.data
  const [pickedKey, setPickedKey] = useState<string | null>(null)
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const [hoverAxis, setHoverAxis] = useState<RadarAxisId | null>(null)
  const selectedKey =
    pickedKey && catalog?.cards.some((card) => card.key === pickedKey)
      ? pickedKey
      : (catalog?.defaultKey ?? null)
  const selected = findCard(catalog?.cards ?? [], selectedKey)
  const compare = useMemo(() => {
    if (!catalog || !hoverKey || hoverKey === selectedKey) return null
    return findCard(catalog.cards, hoverKey)
  }, [catalog, hoverKey, selectedKey])

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
        count={catalog?.cards.length}
        description="Intelligence, coding, agentic, cost, and speed as percentiles versus this joined cohort. Cost is inverted so farther out is cheaper. Missing measurements leave a gap — they are never plotted as zero."
        isFetching={query.isFetching && !query.isPending}
        title="Model card"
      />

      {query.isPending ? <LoadingState label="Loading model cards" rows={5} /> : null}
      {query.isError && !catalog ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {catalog && catalog.cards.length === 0 ? (
        <EmptyState message="No complete models currently have Artificial Analysis metrics to profile." />
      ) : null}

      {catalog && selected ? (
        <>
          <div className="pareto-legend" aria-label="Chart legend">
            <span className="pareto-legend__item">
              <span className="pareto-legend__swatch pareto-legend__swatch--quadrant" />
              This model
            </span>
            <span className="pareto-legend__item">
              <span className="pareto-legend__swatch pareto-legend__swatch--front" />
              Cohort median
            </span>
            <span className="pareto-legend__item">
              <span className="pareto-legend__swatch pareto-legend__swatch--cell task-fit-swatch--empty" />
              Not measured
            </span>
          </div>

          <div className="pareto-layout">
            <figure className="pareto-figure">
              <div className="pareto-chart-frame">
                <ModelCardChart
                  card={selected}
                  compare={compare}
                  hoverAxis={hoverAxis}
                  onHoverAxis={setHoverAxis}
                  variant="interactive"
                />
              </div>
              <figcaption>
                Source: Artificial Analysis indices, cost per Intelligence Index task, and
                median output speed, joined to LMArena. Each axis is a percentile among
                models measured on that axis
                {catalog.indexVersion
                  ? `, using Intelligence Index v${catalog.indexVersion}`
                  : ''}
                . The dashed pentagon is the 50th percentile. Cost is inverted: farther
                from center is cheaper. Filled area is not a single score.
                {` ${RADAR_AXES.map((axis) => `${RADAR_AXIS_META[axis].label} ${catalog.coverage[axis]}/${catalog.cards.length}`).join(' · ')}.`}
              </figcaption>
            </figure>

            <aside className="pareto-aside">
              <Inspector
                axis={hoverAxis}
                point={selected}
                search={location.search}
              />
              <section aria-labelledby="model-card-pick-heading">
                <h2 id="model-card-pick-heading">Pick a model</h2>
                <ol className="pareto-front-list model-card-list">
                  {catalog.cards.map((card) => (
                    <li key={card.key}>
                      <button
                        aria-pressed={selectedKey === card.key}
                        className={`pareto-front-link${selectedKey === card.key ? ' is-active' : ''}${hoverKey === card.key ? ' is-active' : ''}`}
                        onBlur={() => setHoverKey(null)}
                        onClick={() => setPickedKey(card.key)}
                        onFocus={() => setHoverKey(card.key)}
                        onPointerEnter={() => setHoverKey(card.key)}
                        onPointerLeave={() => setHoverKey(null)}
                        type="button"
                      >
                        <span>{card.name}</span>
                        <small>
                          {isCompleteCard(card)
                            ? card.provider
                            : `${card.measuredCount}/5 axes`}
                        </small>
                      </button>
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
  axis,
  search,
}: {
  point: ModelCard
  axis: RadarAxisId | null
  search: string
}) {
  return (
    <section className="pareto-inspector is-filled" aria-live="polite">
      <p className="pareto-inspector__kicker">{point.provider}</p>
      <h2>{point.name}</h2>
      <dl>
        {RADAR_AXES.map((id) => {
          const value = point.axes[id]
          return (
            <div className={axis === id ? 'is-active' : undefined} key={id}>
              <dt>{RADAR_AXIS_META[id].label}</dt>
              <dd>
                {value.raw === null
                  ? 'Not measured'
                  : `${formatRadarRaw(id, value.raw)} · ${formatPercentile(value.percentile)}`}
              </dd>
            </div>
          )
        })}
      </dl>
      <p className="pareto-inspector__flags">
        {isCompleteCard(point)
          ? 'All five axes are measured.'
          : `${RADAR_AXES.length - point.measuredCount} axis${
              RADAR_AXES.length - point.measuredCount === 1 ? '' : 'es'
            } not measured — shown as a gap, not zero.`}
      </p>
      <Link
        className="pareto-inspector__link"
        to={{ pathname: `/models/${encodeURIComponent(point.key)}`, search }}
      >
        Open model page
        <ArrowUpRight aria-hidden="true" size={16} />
      </Link>
    </section>
  )
}
