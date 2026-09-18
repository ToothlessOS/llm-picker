import type { OverviewRow } from '../../api'

export interface ScatterSource {
  key: string
  name: string
  organization: string | null
  intelligence: number | null
  cost: number | null
}

export interface ScatterPoint {
  key: string
  name: string
  provider: string
  providerKey: string
  intelligence: number
  cost: number
  onPareto: boolean
  inAttractiveQuadrant: boolean
}

export interface ScatterModel {
  points: ScatterPoint[]
  pareto: ScatterPoint[]
  omitted: number
  medianCost: number
  medianIntelligence: number
}

const PROVIDER_LABELS: Record<string, string> = {
  alibaba: 'Alibaba',
  anthropic: 'Anthropic',
  deepseek: 'DeepSeek',
  google: 'Google',
  meta: 'Meta',
  minimax: 'MiniMax',
  mistral: 'Mistral',
  moonshot: 'Moonshot',
  openai: 'OpenAI',
  tencent: 'Tencent',
  thinky: 'Thinky',
  xai: 'xAI',
  xiaomi: 'Xiaomi',
  zai: 'Z.ai',
}

export const PROVIDER_PALETTE = [
  '#176b68',
  '#2f6fad',
  '#b45a1b',
  '#7a4e9a',
  '#3d7a4a',
  '#a33b3b',
  '#8b5e06',
  '#1d4e89',
  '#0f766e',
  '#9c4d1a',
  '#4a5568',
  '#6b3fa0',
  '#5c6b2a',
  '#8a3a5c',
] as const

export const LOG_COST_TICKS = [
  0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10,
] as const

export function scatterSourcesFromOverview(
  rows: readonly OverviewRow[],
): ScatterSource[] {
  return rows.map((row) => ({
    key: row.model.key,
    name: row.model.name,
    organization: row.model.organization,
    intelligence: row.aa.intelligence_index,
    cost: row.aa.cost_per_task,
  }))
}

export function providerLabel(organization: string | null): string {
  if (!organization) return 'Unknown'
  return PROVIDER_LABELS[organization] ?? titleCase(organization)
}

export function providerColor(
  providerKey: string,
  providers: readonly string[],
): string {
  const unique = [...new Set(providers)].sort((left, right) =>
    left.localeCompare(right),
  )
  const index = unique.indexOf(providerKey)
  if (index < 0) return PROVIDER_PALETTE[PROVIDER_PALETTE.length - 1]
  return PROVIDER_PALETTE[index % PROVIDER_PALETTE.length]
}

export function formatAxisCurrency(value: number): string {
  if (value >= 1) {
    return new Intl.NumberFormat(undefined, {
      currency: 'USD',
      maximumFractionDigits: 0,
      minimumFractionDigits: 0,
      style: 'currency',
    }).format(value)
  }

  return new Intl.NumberFormat(undefined, {
    currency: 'USD',
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    style: 'currency',
  }).format(value)
}

export function buildScatterModel(
  sources: readonly ScatterSource[],
): ScatterModel {
  const plotted = sources.filter(isPlottable)
  const omitted = sources.length - plotted.length
  const medianCost = median(plotted.map((source) => source.cost))
  const medianIntelligence = median(
    plotted.map((source) => source.intelligence),
  )
  const paretoKeys = new Set(paretoFront(plotted).map((source) => source.key))

  const points = plotted
    .map((source) => {
      const providerKey = source.organization ?? 'unknown'
      return {
        key: source.key,
        name: source.name,
        provider: providerLabel(source.organization),
        providerKey,
        intelligence: source.intelligence,
        cost: source.cost,
        onPareto: paretoKeys.has(source.key),
        inAttractiveQuadrant:
          source.cost < medianCost && source.intelligence > medianIntelligence,
      } satisfies ScatterPoint
    })
    .sort((left, right) => left.cost - right.cost)

  return {
    points,
    pareto: points.filter((point) => point.onPareto),
    omitted,
    medianCost,
    medianIntelligence,
  }
}

function isPlottable(
  source: ScatterSource,
): source is ScatterSource & { intelligence: number; cost: number } {
  return (
    source.intelligence !== null &&
    Number.isFinite(source.intelligence) &&
    source.cost !== null &&
    Number.isFinite(source.cost) &&
    source.cost > 0
  )
}

function paretoFront(
  points: readonly (ScatterSource & { intelligence: number; cost: number })[],
) {
  return points.filter(
    (point) =>
      !points.some(
        (other) =>
          other.key !== point.key &&
          other.cost <= point.cost &&
          other.intelligence >= point.intelligence &&
          (other.cost < point.cost || other.intelligence > point.intelligence),
      ),
  )
}

function median(values: readonly number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 1) return sorted[middle]
  return (sorted[middle - 1] + sorted[middle]) / 2
}

function titleCase(value: string): string {
  return value.replace(/\b[a-z]/g, (letter) => letter.toUpperCase())
}
