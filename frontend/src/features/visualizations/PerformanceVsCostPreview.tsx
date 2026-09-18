import { PerformanceVsCostChart } from './PerformanceVsCostChart'
import { useOverviewScatter } from './useOverviewScatter'

export function PerformanceVsCostPreview() {
  const query = useOverviewScatter()
  const model = query.data
  const hasPoints = Boolean(model && model.points.length > 0)

  return (
    <>
      <div
        aria-busy={query.isPending || undefined}
        className={`viz-stage__canvas viz-stage__canvas--live${query.isPending ? ' is-loading' : ''}`}
      >
        {query.isPending ? (
          <span className="sr-only">Loading performance versus cost chart</span>
        ) : null}
        {query.isError ? (
          <p className="viz-stage__message">Chart unavailable. Open to retry.</p>
        ) : null}
        {hasPoints && model ? (
          <PerformanceVsCostChart model={model} variant="preview" />
        ) : null}
        {query.isSuccess && !hasPoints ? (
          <p className="viz-stage__message">No models with both intelligence and cost.</p>
        ) : null}
      </div>
      {hasPoints && model ? (
        <p className="viz-stage__caption">
          {model.points.length} models · {model.pareto.length} on the Pareto front
        </p>
      ) : null}
    </>
  )
}
