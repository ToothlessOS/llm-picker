import type { OverviewRow } from '../../api'
import { providerLabel, type ScatterModel, type ScatterPoint } from './scatter'
import {
  performanceValue,
  type ParallelRecord,
  type PerformanceMetric,
} from './performanceComparison'

export const SPEED_METRICS = ['output', 'ttft'] as const
export type SpeedMetric = (typeof SPEED_METRICS)[number]

export const SPEED_LABELS: Record<SpeedMetric, string> = {
  output: 'Output speed (tokens/sec)',
  ttft: 'Time to first token (seconds)',
}

/** Output speed is better when larger. Latency is better when smaller. */
export function speedPrefersHigher(metric: SpeedMetric): boolean {
  return metric === 'output'
}

export function speedValue(row: OverviewRow, metric: SpeedMetric): number | null {
  const value = metric === 'output'
    ? row.aa.performance.median_output_tokens_per_second
    : row.aa.performance.median_time_to_first_token_seconds
  return value !== null && Number.isFinite(value) && value > 0 ? value : null
}

export function formatSpeed(value: number | null, metric: SpeedMetric): string {
  if (value === null || !Number.isFinite(value)) return 'Not measured'
  if (metric === 'output') {
    return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value)} tok/s`
  }
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)} s`
}

/** Same cohort as the cost parallel chart, with the active speed measure on the first axis. */
export function buildSpeedParallelRecords(
  rows: readonly OverviewRow[],
  metric: SpeedMetric,
): ParallelRecord[] {
  return rows.map((row) => {
    const finite = (value: number | null) =>
      value !== null && Number.isFinite(value) ? value : null
    return {
      key: row.model.key,
      name: row.model.name,
      providerKey: row.model.organization ?? 'unknown',
      cost: null,
      speed: speedValue(row, metric),
      intelligence: finite(performanceValue(row, 'intelligence')),
      coding: finite(performanceValue(row, 'coding')),
      agent: finite(performanceValue(row, 'agent')),
    }
  })
}

export function buildSpeedComparison(
  rows: readonly OverviewRow[],
  performance: PerformanceMetric,
  speed: SpeedMetric,
  provider: string | null,
): ScatterModel & { xDomain: [number, number] } {
  const cohort = rows.filter((row) => provider === null || row.model.organization === provider)
  const plotted = cohort.flatMap((row) => {
    const score = performanceValue(row, performance)
    const pace = speedValue(row, speed)
    if (score === null || !Number.isFinite(score) || pace === null) return []
    return [{ row, score, pace }]
  })
  const paces = plotted.map((item) => item.pace)
  const min = paces.length ? Math.min(...paces) : 1
  const max = paces.length ? Math.max(...paces) : 1
  const xDomain: [number, number] = speed === 'ttft'
    ? [min * 0.8, max === min ? max * 1.5 : max * 1.2]
    : [0, max > 0 ? max * 1.08 : 1]
  const medianPace = median(paces)
  const medianScore = median(plotted.map((item) => item.score))
  const higher = speedPrefersHigher(speed)
  const paretoKeys = new Set(pareto(plotted, higher).map((item) => item.row.model.key))
  const points = plotted
    .map((item) => {
      const providerKey = item.row.model.organization ?? 'unknown'
      return {
        key: item.row.model.key,
        name: item.row.model.name,
        provider: providerLabel(item.row.model.organization),
        providerKey,
        intelligence: item.score,
        cost: item.pace,
        onPareto: paretoKeys.has(item.row.model.key),
        inAttractiveQuadrant: item.score > medianScore &&
          (higher ? item.pace > medianPace : item.pace < medianPace),
      } satisfies ScatterPoint
    })
    .sort((left, right) => left.cost - right.cost)

  return {
    points,
    pareto: points.filter((point) => point.onPareto),
    omitted: cohort.length - plotted.length,
    medianCost: medianPace,
    medianIntelligence: medianScore,
    xDomain,
  }
}

function pareto(
  points: readonly { row: OverviewRow; score: number; pace: number }[],
  higherPaceIsBetter: boolean,
) {
  return points.filter((point) => !points.some((other) => {
    if (other.row.model.key === point.row.model.key) return false
    const paceBetter = higherPaceIsBetter ? other.pace >= point.pace : other.pace <= point.pace
    const paceStrict = higherPaceIsBetter ? other.pace > point.pace : other.pace < point.pace
    return paceBetter && other.score >= point.score && (paceStrict || other.score > point.score)
  }))
}

function median(values: readonly number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}
