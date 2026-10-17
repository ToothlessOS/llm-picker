import type { OverviewRow } from '../../api'
import { buildScatterModel, type ScatterModel } from './scatter'

export const PERFORMANCE_METRICS = ['intelligence', 'coding', 'agent'] as const
export type PerformanceMetric = (typeof PERFORMANCE_METRICS)[number]
export type CostMetric = 'task' | 'input' | 'output'
export type CostScale = 'log' | 'linear'

export const PERFORMANCE_LABELS: Record<PerformanceMetric, string> = {
  intelligence: 'AA Intelligence Index',
  coding: 'AA Coding Index',
  agent: 'LMArena Agent Score',
}

export const COST_LABELS: Record<CostMetric, string> = {
  task: 'AA cost per Intelligence Index task (USD)',
  input: 'Input price per million tokens (USD)',
  output: 'Output price per million tokens (USD)',
}

export function performanceValue(row: OverviewRow, metric: PerformanceMetric) {
  if (metric === 'agent') return row.categories.agent.metric_value
  return metric === 'coding' ? row.aa.coding_index : row.aa.intelligence_index
}

export function costValue(row: OverviewRow, metric: CostMetric) {
  if (metric === 'task') return row.aa.cost_per_task
  return metric === 'input'
    ? row.aa.pricing.price_1m_input_tokens
    : row.aa.pricing.price_1m_output_tokens
}

export function measurableCost(value: number | null, scale: CostScale): value is number {
  return value !== null && Number.isFinite(value) &&
    (scale === 'log' ? value > 0 : value >= 0)
}

export function buildPerformanceComparison(
  rows: readonly OverviewRow[],
  costMetric: CostMetric,
  scale: CostScale,
  provider: string | null,
): { models: Record<PerformanceMetric, ScatterModel>; xDomain: [number, number]; rows: OverviewRow[] } {
  const cohort = rows.filter((row) => provider === null || row.model.organization === provider)
  const costs = cohort.map((row) => costValue(row, costMetric))
    .filter((value) => measurableCost(value, scale))
  const min = costs.length ? Math.min(...costs) : 1
  const max = costs.length ? Math.max(...costs) : 1
  const xDomain: [number, number] = scale === 'log'
    ? [min * 0.8, max === min ? max * 1.5 : max * 1.2]
    : [0, max > 0 ? max * 1.12 : 1]
  const models = Object.fromEntries(PERFORMANCE_METRICS.map((metric) => {
    // The original scatter model's `intelligence` field holds the selected Y value.
    const model = buildScatterModel(cohort.map((row) => ({
      key: row.model.key,
      name: row.model.name,
      organization: row.model.organization,
      cost: measurableCost(costValue(row, costMetric), scale) ? costValue(row, costMetric) : null,
      intelligence: performanceValue(row, metric),
    })), { allowZeroCost: scale === 'linear' })
    return [metric, model]
  })) as Record<PerformanceMetric, ScatterModel>
  return { models, rows: cohort, xDomain }
}

export function keysInScatterBounds(
  model: ScatterModel,
  bounds: { x: readonly [number, number]; y: readonly [number, number] },
): string[] {
  return model.points.filter((point) =>
    point.cost >= bounds.x[0] && point.cost <= bounds.x[1] &&
    point.intelligence >= bounds.y[0] && point.intelligence <= bounds.y[1],
  ).map((point) => point.key)
}

export function toggleComparedModel(current: readonly string[], key: string): string[] {
  if (current.includes(key)) return current.filter((item) => item !== key)
  return current.length < 3 ? [...current, key] : [...current]
}

export function formatPerformance(value: number | null, metric: PerformanceMetric): string {
  return value === null || !Number.isFinite(value) ? 'Not measured' :
    new Intl.NumberFormat(undefined, { maximumFractionDigits: metric === 'agent' ? 4 : 1 }).format(value)
}
