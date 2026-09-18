import { CostPerTaskChart } from './CostPerTaskChart'
import { useOverviewCostBars } from './useOverviewScatter'

export function CostPerTaskPreview() {
  const query = useOverviewCostBars()
  const model = query.data
  const hasBars = Boolean(model && model.bars.length > 0)

  return (
    <>
      <div
        aria-busy={query.isPending || undefined}
        className={`viz-stage__canvas viz-stage__canvas--live${query.isPending ? ' is-loading' : ''}`}
      >
        {query.isPending ? (
          <span className="sr-only">Loading cost per task chart</span>
        ) : null}
        {query.isError ? (
          <p className="viz-stage__message">Chart unavailable. Open to retry.</p>
        ) : null}
        {hasBars && model ? (
          <CostPerTaskChart model={model} variant="preview" />
        ) : null}
        {query.isSuccess && !hasBars ? (
          <p className="viz-stage__message">No models with a measured cost per task.</p>
        ) : null}
      </div>
      {hasBars && model ? (
        <p className="viz-stage__caption">
          {model.bars.length} model{model.bars.length === 1 ? '' : 's'} · list-price mix, not
          usage
        </p>
      ) : null}
    </>
  )
}
