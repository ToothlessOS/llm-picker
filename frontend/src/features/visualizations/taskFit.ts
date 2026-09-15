import {
  CATEGORIES,
  type Category,
  type CategoryBlock,
  type CategoryBlocks,
  type MetricKind,
  type OverviewRow,
} from '../../api'

import { providerLabel } from './scatter'

export const TASK_CATEGORIES = CATEGORIES

export const TASK_CATEGORY_META: Record<
  Category,
  { label: string; short: string }
> = {
  agent: { label: 'Agent', short: 'Agent' },
  document: { label: 'Document', short: 'Docs' },
  search: { label: 'Search', short: 'Search' },
  webdev: { label: 'WebDev', short: 'Web' },
}

export interface TaskFitSource {
  key: string
  name: string
  organization: string | null
  categories: CategoryBlocks
}

export interface TaskCell {
  category: Category
  evaluated: boolean
  rank: number | null
  metric: number | null
  metricKind: MetricKind | null
  sampleSize: number | null
}

export interface RankExtent {
  min: number
  max: number
}

export interface TaskFitRow {
  key: string
  name: string
  provider: string
  providerKey: string
  cells: Record<Category, TaskCell>
  evaluatedCount: number
  bestCategory: Category | null
}

export interface TaskFitModel {
  rows: TaskFitRow[]
  omitted: number
  coverage: Record<Category, number>
  rankExtent: Record<Category, RankExtent | null>
}

export function taskFitSourcesFromOverview(
  rows: readonly OverviewRow[],
): TaskFitSource[] {
  return rows.map((row) => ({
    key: row.model.key,
    name: row.model.name,
    organization: row.model.organization,
    categories: row.categories,
  }))
}

export function buildTaskFitModel(
  sources: readonly TaskFitSource[],
): TaskFitModel {
  const rows = sources.map(toRow)
  const coverage = Object.fromEntries(
    TASK_CATEGORIES.map((category) => [
      category,
      rows.filter((row) => row.cells[category].evaluated).length,
    ]),
  ) as Record<Category, number>
  const rankExtent = Object.fromEntries(
    TASK_CATEGORIES.map((category) => [category, extentFor(rows, category)]),
  ) as Record<Category, RankExtent | null>

  return {
    coverage,
    omitted: 0,
    rankExtent,
    rows: sortTaskFitRows(rows, 'agent'),
  }
}

export function sortTaskFitRows(
  rows: readonly TaskFitRow[],
  category: Category,
): TaskFitRow[] {
  return [...rows].sort((left, right) => {
    const rankDelta =
      rankSortValue(left.cells[category]) - rankSortValue(right.cells[category])
    if (rankDelta !== 0) return rankDelta
    const agentDelta =
      rankSortValue(left.cells.agent) - rankSortValue(right.cells.agent)
    if (agentDelta !== 0) return agentDelta
    return left.name.localeCompare(right.name)
  })
}

export function bestAtTask(
  rows: readonly TaskFitRow[],
  category: Category,
  limit = 6,
): TaskFitRow[] {
  return sortTaskFitRows(rows, category)
    .filter((row) => row.cells[category].rank !== null)
    .slice(0, limit)
}

export function rankStrength(rank: number, extent: RankExtent): number {
  if (!(rank > 0) || !(extent.min > 0) || !(extent.max > 0)) return 0
  if (extent.max <= extent.min) return 1
  if (rank <= extent.min) return 1
  if (rank >= extent.max) return 0
  const start = Math.log(extent.min)
  const end = Math.log(extent.max)
  return 1 - (Math.log(rank) - start) / (end - start)
}

export function formatTaskRank(cell: TaskCell): string {
  if (!cell.evaluated) return 'Not evaluated'
  if (cell.rank === null) return 'Not ranked'
  return `#${cell.rank}`
}

export function formatTaskMetric(cell: TaskCell): string {
  if (!cell.evaluated) return 'Not evaluated'
  if (cell.metric === null) return 'Not measured'
  if (cell.metricKind === 'score') {
    return new Intl.NumberFormat(undefined, {
      maximumFractionDigits: 3,
      minimumFractionDigits: 3,
      signDisplay: 'exceptZero',
    }).format(cell.metric)
  }
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(
    cell.metric,
  )
}

export function taskFitCoverageCaption(model: TaskFitModel): string {
  return TASK_CATEGORIES.map(
    (category) =>
      `${TASK_CATEGORY_META[category].label} ${model.coverage[category]}/${model.rows.length}`,
  ).join(' · ')
}

function toRow(source: TaskFitSource): TaskFitRow {
  const cells = Object.fromEntries(
    TASK_CATEGORIES.map((category) => [
      category,
      toCell(category, source.categories[category]),
    ]),
  ) as Record<Category, TaskCell>
  const evaluatedCount = TASK_CATEGORIES.filter(
    (category) => cells[category].evaluated,
  ).length

  return {
    bestCategory: bestCategoryOf(cells),
    cells,
    evaluatedCount,
    key: source.key,
    name: source.name,
    provider: providerLabel(source.organization),
    providerKey: source.organization ?? 'unknown',
  }
}

function toCell(category: Category, block: CategoryBlock | null): TaskCell {
  if (!block) {
    return {
      category,
      evaluated: false,
      metric: null,
      metricKind: null,
      rank: null,
      sampleSize: null,
    }
  }

  return {
    category,
    evaluated: true,
    metric: block.metric_value,
    metricKind: block.metric_kind,
    rank: block.rank,
    sampleSize: block.sample_size,
  }
}

function bestCategoryOf(cells: Record<Category, TaskCell>): Category | null {
  let best: Category | null = null
  let bestRank = Number.POSITIVE_INFINITY
  for (const category of TASK_CATEGORIES) {
    const rank = cells[category].rank
    if (rank === null) continue
    if (rank < bestRank) {
      best = category
      bestRank = rank
    }
  }
  return best
}

function extentFor(
  rows: readonly TaskFitRow[],
  category: Category,
): RankExtent | null {
  const ranks = rows
    .map((row) => row.cells[category].rank)
    .filter((rank): rank is number => rank !== null && rank > 0)
  if (ranks.length === 0) return null
  return { max: Math.max(...ranks), min: Math.min(...ranks) }
}

function rankSortValue(cell: TaskCell): number {
  return cell.rank ?? Number.POSITIVE_INFINITY
}
