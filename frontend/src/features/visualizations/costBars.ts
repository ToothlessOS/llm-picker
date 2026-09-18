import type { OverviewRow } from '../../api'

import { providerLabel } from './scatter'

export const COST_SEGMENT_IDS = [
  'input',
  'output',
  'cacheWrite',
  'cacheHit',
  'unspecified',
] as const

export type CostSegmentId = (typeof COST_SEGMENT_IDS)[number]

export interface CostBarSource {
  key: string
  name: string
  organization: string | null
  cost: number | null
  input: number | null
  output: number | null
  cacheHit: number | null
  cacheWrite: number | null
}

export interface CostSegment {
  id: CostSegmentId
  label: string
  price: number | null
  value: number
}

export interface CostBar {
  key: string
  name: string
  provider: string
  providerKey: string
  cost: number
  segments: CostSegment[]
}

export interface CostBarModel {
  bars: CostBar[]
  omitted: number
  medianCost: number
}

export const COST_SEGMENT_META: Record<
  Exclude<CostSegmentId, 'unspecified'>,
  { label: string; token: string }
> = {
  input: { label: 'Input', token: '--color-cost-input' },
  output: { label: 'Output', token: '--color-cost-output' },
  cacheWrite: { label: 'Cache write', token: '--color-cost-cache-write' },
  cacheHit: { label: 'Cache hit', token: '--color-cost-cache-hit' },
}

export function costBarSourcesFromOverview(
  rows: readonly OverviewRow[],
): CostBarSource[] {
  return rows.map((row) => ({
    key: row.model.key,
    name: row.model.name,
    organization: row.model.organization,
    cost: row.aa.cost_per_task,
    input: row.aa.pricing.price_1m_input_tokens,
    output: row.aa.pricing.price_1m_output_tokens,
    cacheHit: row.aa.pricing.price_1m_cache_hit_tokens,
    cacheWrite: row.aa.pricing.price_1m_cache_write_tokens,
  }))
}

export function buildCostBarModel(
  sources: readonly CostBarSource[],
): CostBarModel {
  const plotted = sources.filter(hasMeasuredCost)
  return {
    bars: plotted
      .map((source) => {
        const providerKey = source.organization ?? 'unknown'
        return {
          key: source.key,
          name: source.name,
          provider: providerLabel(source.organization),
          providerKey,
          cost: source.cost,
          segments: allocateCost(source),
        } satisfies CostBar
      })
      .sort((left, right) => left.cost - right.cost),
    omitted: sources.length - plotted.length,
    medianCost: median(plotted.map((source) => source.cost)),
  }
}

export function formatBarAxisCurrency(value: number): string {
  const nearest = Math.round(value)
  const isWhole = Math.abs(value - nearest) < 1e-6
  return new Intl.NumberFormat(undefined, {
    currency: 'USD',
    maximumFractionDigits: isWhole ? 0 : 2,
    minimumFractionDigits: isWhole ? 0 : 2,
    style: 'currency',
  }).format(isWhole ? nearest : value)
}

export function shortModelName(name: string, limit = 22): string {
  if (name.length <= limit) return name
  return `${name.slice(0, Math.max(limit - 1, 1))}…`
}

function hasMeasuredCost(
  source: CostBarSource,
): source is CostBarSource & { cost: number } {
  return source.cost !== null && Number.isFinite(source.cost) && source.cost > 0
}

function allocateCost(source: CostBarSource & { cost: number }): CostSegment[] {
  const priced = [
    segment('input', source.input),
    segment('output', source.output),
    segment('cacheWrite', source.cacheWrite),
    segment('cacheHit', source.cacheHit),
  ].filter((item): item is CostSegment & { price: number } => item.price !== null)

  const weight = priced.reduce((sum, item) => sum + Math.max(item.price, 0), 0)
  if (priced.length === 0 || weight === 0) {
    return [
      {
        id: 'unspecified',
        label: 'Unspecified',
        price: null,
        value: source.cost,
      },
    ]
  }

  return priced.map((item) => ({
    ...item,
    value: source.cost * (Math.max(item.price, 0) / weight),
  }))
}

function segment(
  id: Exclude<CostSegmentId, 'unspecified'>,
  price: number | null,
): CostSegment {
  return {
    id,
    label: COST_SEGMENT_META[id].label,
    price,
    value: 0,
  }
}

function median(values: readonly number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 1) return sorted[middle]
  return (sorted[middle - 1] + sorted[middle]) / 2
}
