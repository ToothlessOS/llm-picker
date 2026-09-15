import { TaskFitChart } from './TaskFitChart'
import { useOverviewTaskFit } from './useOverviewScatter'

export function TaskFitPreview() {
  const query = useOverviewTaskFit()
  const model = query.data
  const hasRows = Boolean(model && model.rows.length > 0)

  return (
    <>
      <div
        aria-busy={query.isPending || undefined}
        className={`viz-stage__canvas viz-stage__canvas--live${query.isPending ? ' is-loading' : ''}`}
      >
        {query.isPending ? (
          <span className="sr-only">Loading task fit chart</span>
        ) : null}
        {query.isError ? (
          <p className="viz-stage__message">Chart unavailable. Open to retry.</p>
        ) : null}
        {hasRows && model ? (
          <TaskFitChart model={model} variant="preview" />
        ) : null}
        {query.isSuccess && !hasRows ? (
          <p className="viz-stage__message">No complete models to compare across tasks.</p>
        ) : null}
      </div>
      {hasRows && model ? (
        <p className="viz-stage__caption">
          {model.rows.length} models · ranks across 4 tasks
        </p>
      ) : null}
    </>
  )
}
