import { useCallback, useMemo, useState } from 'react'
import { ArrowLeft, ArrowUpRight } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { type Category } from '../../api'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'
import { TaskFitChart } from './TaskFitChart'
import {
  TASK_CATEGORIES,
  TASK_CATEGORY_META,
  bestAtTask,
  formatTaskMetric,
  formatTaskRank,
  sortTaskFitRows,
  taskFitCoverageCaption,
  type TaskFitRow,
} from './taskFit'
import { useOverviewTaskFit } from './useOverviewScatter'

export function TaskFitPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const query = useOverviewTaskFit()
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const [sortCategory, setSortCategory] = useState<Category>('agent')
  const model = query.data
  const rows = useMemo(
    () => (model ? sortTaskFitRows(model.rows, sortCategory) : []),
    [model, sortCategory],
  )
  const viewModel = useMemo(
    () => (model ? { ...model, rows } : null),
    [model, rows],
  )
  const hovered = rows.find((row) => row.key === hoverKey) ?? null
  const leaders = useMemo(
    () => bestAtTask(rows, sortCategory),
    [rows, sortCategory],
  )

  const onSelect = useCallback(
    (key: string) => {
      navigate({
        pathname: `/models/${encodeURIComponent(key)}`,
        search: location.search,
      })
    },
    [location.search, navigate],
  )

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
        count={model?.rows.length}
        description="LMArena ranks across agent, document, search, and webdev. Color is relative to ranks in that task among these models — Agent scores and the other ratings are never mixed."
        isFetching={query.isFetching && !query.isPending}
        title="Task fit"
      />

      {query.isPending ? <LoadingState label="Loading task fit" rows={5} /> : null}
      {query.isError && !model ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : null}
      {model && model.rows.length === 0 ? (
        <EmptyState message="No complete models currently have LMArena task ranks." />
      ) : null}

      {viewModel && viewModel.rows.length > 0 ? (
        <>
          <div className="pareto-legend" aria-label="Chart legend">
            <span className="pareto-legend__item">
              <span className="pareto-legend__swatch pareto-legend__swatch--cell task-fit-swatch--best" />
              Better rank
            </span>
            <span className="pareto-legend__item">
              <span className="pareto-legend__swatch pareto-legend__swatch--cell task-fit-swatch--worst" />
              Worse rank
            </span>
            <span className="pareto-legend__item">
              <span className="pareto-legend__swatch pareto-legend__swatch--cell task-fit-swatch--empty" />
              Not evaluated
            </span>
            {TASK_CATEGORIES.map((category) => (
              <button
                aria-pressed={sortCategory === category}
                className={`pareto-legend__item pareto-legend__item--provider${sortCategory === category ? ' is-pinned' : ''}`}
                key={category}
                onClick={() => setSortCategory(category)}
                type="button"
              >
                {TASK_CATEGORY_META[category].label}
              </button>
            ))}
          </div>

          <div className="pareto-layout">
            <figure className="pareto-figure">
              <div className="pareto-chart-frame">
                <TaskFitChart
                  hoverKey={hoverKey}
                  model={viewModel}
                  onHover={setHoverKey}
                  onSelect={onSelect}
                  onSort={setSortCategory}
                  sortCategory={sortCategory}
                  variant="interactive"
                />
              </div>
              <figcaption>
                Source: LMArena category ranks, joined to complete Artificial Analysis
                matches. Each column is ranked on its own ladder — Agent publishes a
                score, the others publish ratings. Empty cells were not evaluated, never
                plotted as zero. {taskFitCoverageCaption(viewModel)}.
                {viewModel.coverage.search <= 2
                  ? ' Search is sparse in the joined set.'
                  : ''}
              </figcaption>
            </figure>

            <aside className="pareto-aside">
              <Inspector
                point={hovered}
                search={location.search}
                sortCategory={sortCategory}
              />
              <section aria-labelledby="task-fit-best-heading">
                <h2 id="task-fit-best-heading">
                  Best at {TASK_CATEGORY_META[sortCategory].label}
                </h2>
                {leaders.length === 0 ? (
                  <p className="pareto-inspector__empty">
                    None of these models were evaluated on this task.
                  </p>
                ) : (
                  <ol className="pareto-front-list">
                    {leaders.map((row) => (
                      <li key={row.key}>
                        <Link
                          className={`pareto-front-link${hoverKey === row.key ? ' is-active' : ''}`}
                          onBlur={() => setHoverKey(null)}
                          onFocus={() => setHoverKey(row.key)}
                          onPointerEnter={() => setHoverKey(row.key)}
                          onPointerLeave={() => setHoverKey(null)}
                          to={{
                            pathname: `/models/${encodeURIComponent(row.key)}`,
                            search: location.search,
                          }}
                        >
                          <span>{row.name}</span>
                          <small>{formatTaskRank(row.cells[sortCategory])}</small>
                        </Link>
                      </li>
                    ))}
                  </ol>
                )}
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
  search,
  sortCategory,
}: {
  point: TaskFitRow | null
  search: string
  sortCategory: Category
}) {
  if (!point) {
    return (
      <section className="pareto-inspector" aria-live="polite">
        <p className="pareto-inspector__kicker">Explore</p>
        <h2>Hover a model</h2>
        <p>
          Each cell is that model&apos;s LMArena rank on that task. Stronger teal is
          a better rank in that column. Click a task name to sort. Click a row to open
          the model card.
        </p>
      </section>
    )
  }

  const best = point.bestCategory

  return (
    <section className="pareto-inspector is-filled" aria-live="polite">
      <p className="pareto-inspector__kicker">{point.provider}</p>
      <h2>{point.name}</h2>
      <dl>
        {TASK_CATEGORIES.map((category) => {
          const cell = point.cells[category]
          return (
            <div key={category}>
              <dt>{TASK_CATEGORY_META[category].label}</dt>
              <dd>
                {cell.evaluated
                  ? `${formatTaskRank(cell)}${
                      cell.metric === null
                        ? ''
                        : ` · ${cell.metricKind} ${formatTaskMetric(cell)}`
                    }`
                  : 'Not evaluated'}
              </dd>
            </div>
          )
        })}
      </dl>
      <p className="pareto-inspector__flags">
        {best
          ? `Strongest rank is ${TASK_CATEGORY_META[best].label} (${formatTaskRank(point.cells[best])}).`
          : 'No published ranks on these tasks.'}
        {point.cells[sortCategory].evaluated
          ? ''
          : ` Not evaluated on ${TASK_CATEGORY_META[sortCategory].label}.`}
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
