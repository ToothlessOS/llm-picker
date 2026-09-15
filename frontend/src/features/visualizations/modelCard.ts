import type { OverviewRow } from '../../api'

import { providerLabel } from './scatter'

export const RADAR_AXES = [
  'intelligence',
  'coding',
  'agentic',
  'cost',
  'speed',
] as const

export type RadarAxisId = (typeof RADAR_AXES)[number]

export const RADAR_AXIS_META: Record<
  RadarAxisId,
  { label: string; short: string; invert: boolean }
> = {
  intelligence: { invert: false, label: 'Intelligence', short: 'Intel' },
  coding: { invert: false, label: 'Coding', short: 'Code' },
  agentic: { invert: false, label: 'Agentic', short: 'Agentic' },
  cost: { invert: true, label: 'Cost', short: 'Cost' },
  speed: { invert: false, label: 'Speed', short: 'Speed' },
}

export interface ModelCardSource {
  key: string
  name: string
  organization: string | null
  intelligence: number | null
  coding: number | null
  agentic: number | null
  cost: number | null
  speed: number | null
  indexVersion: number | null
}

export interface RadarAxisValue {
  id: RadarAxisId
  raw: number | null
  percentile: number | null
}

export interface ModelCard {
  key: string
  name: string
  provider: string
  providerKey: string
  axes: Record<RadarAxisId, RadarAxisValue>
  measuredCount: number
}

export interface ModelCardCatalog {
  cards: ModelCard[]
  omitted: number
  defaultKey: string | null
  coverage: Record<RadarAxisId, number>
  indexVersion: number | null
}

export function modelCardSourcesFromOverview(
  rows: readonly OverviewRow[],
): ModelCardSource[] {
  return rows.map((row) => ({
    agentic: row.aa.agentic_index,
    coding: row.aa.coding_index,
    cost: row.aa.cost_per_task,
    indexVersion: row.aa.intelligence_index_version,
    intelligence: row.aa.intelligence_index,
    key: row.model.key,
    name: row.model.name,
    organization: row.model.organization,
    speed: row.aa.performance.median_output_tokens_per_second,
  }))
}

export function buildModelCardCatalog(
  sources: readonly ModelCardSource[],
): ModelCardCatalog {
  const pools = Object.fromEntries(
    RADAR_AXES.map((axis) => [axis, poolFor(sources, axis)]),
  ) as Record<RadarAxisId, number[]>
  const cards = sources
    .map((source) => toCard(source, pools))
    .sort((left, right) => {
      const intelDelta =
        (right.axes.intelligence.raw ?? Number.NEGATIVE_INFINITY) -
        (left.axes.intelligence.raw ?? Number.NEGATIVE_INFINITY)
      if (intelDelta !== 0) return intelDelta
      return left.name.localeCompare(right.name)
    })
  const coverage = Object.fromEntries(
    RADAR_AXES.map((axis) => [axis, pools[axis].length]),
  ) as Record<RadarAxisId, number>
  const versions = [
    ...new Set(
      sources
        .map((source) => source.indexVersion)
        .filter((version): version is number => version !== null),
    ),
  ]

  return {
    cards,
    coverage,
    defaultKey: pickDefaultKey(cards),
    indexVersion: versions.length === 1 ? versions[0] : null,
    omitted: 0,
  }
}

export function findCard(
  cards: readonly ModelCard[],
  key: string | null,
): ModelCard | null {
  if (!key) return null
  return cards.find((card) => card.key === key) ?? null
}

export function isCompleteCard(card: ModelCard): boolean {
  return card.measuredCount === RADAR_AXES.length
}

export function percentileAmong(
  value: number,
  pool: readonly number[],
  invert = false,
): number | null {
  if (!Number.isFinite(value) || pool.length === 0) return null
  const count = invert
    ? pool.filter((item) => item >= value).length
    : pool.filter((item) => item <= value).length
  return count / pool.length
}

export function formatRadarRaw(axis: RadarAxisId, value: number | null): string {
  if (value === null) return 'Not measured'
  if (axis === 'cost') {
    return new Intl.NumberFormat(undefined, {
      currency: 'USD',
      maximumFractionDigits: 4,
      style: 'currency',
    }).format(value)
  }
  if (axis === 'speed') {
    return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value)} tok/s`
  }
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
  }).format(value)
}

export function formatPercentile(value: number | null): string {
  if (value === null) return 'Not measured'
  const pct = Math.round(value * 100)
  return `${pct}${ordinal(pct)}`
}

function toCard(
  source: ModelCardSource,
  pools: Record<RadarAxisId, number[]>,
): ModelCard {
  const axes = Object.fromEntries(
    RADAR_AXES.map((axis) => {
      const raw = rawFor(source, axis)
      return [
        axis,
        {
          id: axis,
          percentile:
            raw === null
              ? null
              : percentileAmong(raw, pools[axis], RADAR_AXIS_META[axis].invert),
          raw,
        } satisfies RadarAxisValue,
      ]
    }),
  ) as Record<RadarAxisId, RadarAxisValue>

  return {
    axes,
    key: source.key,
    measuredCount: RADAR_AXES.filter((axis) => axes[axis].percentile !== null)
      .length,
    name: source.name,
    provider: providerLabel(source.organization),
    providerKey: source.organization ?? 'unknown',
  }
}

function pickDefaultKey(cards: readonly ModelCard[]): string | null {
  const complete = cards.find(isCompleteCard)
  if (complete) return complete.key
  return cards[0]?.key ?? null
}

function rawFor(source: ModelCardSource, axis: RadarAxisId): number | null {
  if (axis === 'cost' || axis === 'speed') {
    return measuredPositive(source[axis]) ? source[axis] : null
  }
  return measuredIndex(source[axis]) ? source[axis] : null
}

function poolFor(sources: readonly ModelCardSource[], axis: RadarAxisId): number[] {
  return sources
    .map((source) => rawFor(source, axis))
    .filter((value): value is number => value !== null)
}

function measuredIndex(value: number | null): value is number {
  return value !== null && Number.isFinite(value)
}

function measuredPositive(value: number | null): value is number {
  return value !== null && Number.isFinite(value) && value > 0
}

function ordinal(value: number): string {
  const teen = value % 100
  if (teen >= 11 && teen <= 13) return 'th'
  switch (value % 10) {
    case 1:
      return 'st'
    case 2:
      return 'nd'
    case 3:
      return 'rd'
    default:
      return 'th'
  }
}
