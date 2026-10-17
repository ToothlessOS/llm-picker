import type { OverviewRow } from '../../api'
import { providerLabel } from '../visualizations/scatter'

export interface ReleaseNote {
  key: string
  creator: string
  name: string
  releasedOn: string
}

export function latestReleases(rows: readonly OverviewRow[], limit = 3): ReleaseNote[] {
  return rows
    .flatMap((row) => {
      const releasedOn = row.aa.release_date
      if (!releasedOn) return []
      const creator = row.aa.creator?.name || providerLabel(row.model.organization)
      return [{
        key: row.model.key,
        creator,
        name: row.model.name,
        releasedOn,
      }]
    })
    .sort((left, right) => right.releasedOn.localeCompare(left.releasedOn) || left.name.localeCompare(right.name))
    .slice(0, limit)
}

export function formatReleaseDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(`${value}T00:00:00`))
}
