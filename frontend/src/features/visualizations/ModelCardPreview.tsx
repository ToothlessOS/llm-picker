import { ModelCardChart } from './ModelCardChart'
import { findCard } from './modelCard'
import { shortModelName } from './costBars'
import { useOverviewModelCard } from './useOverviewScatter'

export function ModelCardPreview() {
  const query = useOverviewModelCard()
  const catalog = query.data
  const featured = catalog ? findCard(catalog.cards, catalog.defaultKey) : null

  return (
    <>
      <div
        aria-busy={query.isPending || undefined}
        className={`viz-stage__canvas viz-stage__canvas--live${query.isPending ? ' is-loading' : ''}`}
      >
        {query.isPending ? (
          <span className="sr-only">Loading model card chart</span>
        ) : null}
        {query.isError ? (
          <p className="viz-stage__message">Chart unavailable. Open to retry.</p>
        ) : null}
        {featured ? <ModelCardChart card={featured} variant="preview" /> : null}
        {query.isSuccess && !featured ? (
          <p className="viz-stage__message">No complete models to profile.</p>
        ) : null}
      </div>
      {featured ? (
        <p className="viz-stage__caption">
          {shortModelName(featured.name, 28)} vs cohort median
        </p>
      ) : null}
    </>
  )
}
