import { AlertTriangle, Clock3, CircleOff } from 'lucide-react'

import {
  getFreshnessState,
  type FreshnessState,
  type MetadataResponse,
} from '../../api'
import { formatDateTime } from '../../app/format'

const sourceLabels = {
  lmarena: 'LMArena',
  artificial_analysis: 'Artificial Analysis',
} as const

const stateIcons: Record<Exclude<FreshnessState, 'fresh'>, typeof Clock3> = {
  stale: Clock3,
  refresh_failed: AlertTriangle,
  never_refreshed: Clock3,
  not_configured: CircleOff,
}

interface FreshnessBannerProps {
  metadata?: MetadataResponse
}

export function FreshnessBanner({ metadata }: FreshnessBannerProps) {
  if (!metadata) return null

  const issues = Object.entries(metadata.sources)
    .map(([source, freshness]) => ({
      source: source as keyof typeof sourceLabels,
      freshness,
      state: getFreshnessState(freshness),
    }))
    .filter(({ state }) => state !== 'fresh')

  if (issues.length === 0) return null

  return (
    <div className="freshness-banner" role="status">
      {issues.map(({ source, freshness, state }) => {
        const Icon = stateIcons[state as Exclude<FreshnessState, 'fresh'>]
        const detail = {
          stale: `Last successful update ${formatDateTime(freshness.last_success_at)}.`,
          refresh_failed: `The latest refresh failed; showing data from ${formatDateTime(freshness.last_success_at)}.`,
          never_refreshed: 'Waiting for the first successful refresh.',
          not_configured: 'This source is not configured.',
          fresh: '',
        }[state]

        return (
          <div className="freshness-banner__item" key={source}>
            <Icon aria-hidden="true" size={18} />
            <p>
              <strong>{sourceLabels[source]}</strong> {detail}
            </p>
          </div>
        )
      })}
    </div>
  )
}
