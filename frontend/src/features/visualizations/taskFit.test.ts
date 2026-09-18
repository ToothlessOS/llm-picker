import { describe, expect, it } from 'vitest'

import type { CategoryBlock, CategoryBlocks } from '../../api'

import {
  bestAtTask,
  buildTaskFitModel,
  formatTaskMetric,
  formatTaskRank,
  rankStrength,
  sortTaskFitRows,
  type TaskFitSource,
} from './taskFit'

function block(
  category: CategoryBlock['category'],
  input: {
    kind: CategoryBlock['metric_kind']
    rank: number | null
    value: number | null
  },
): CategoryBlock {
  return {
    category,
    leaderboard_publish_date: '2026-09-01',
    license: null,
    matched_by_fold: false,
    metric_kind: input.kind,
    metric_lower: null,
    metric_upper: null,
    metric_value: input.value,
    metric_variance: null,
    model_name: 'model',
    organization: 'openai',
    rank: input.rank,
    sample_size: 10,
    session_count: 10,
    source_key: 'model',
  }
}

function source(
  key: string,
  categories: Partial<CategoryBlocks> & Pick<CategoryBlocks, 'agent'>,
): TaskFitSource {
  return {
    key,
    name: key,
    organization: 'openai',
    categories: {
      agent: categories.agent,
      document: categories.document ?? null,
      search: categories.search ?? null,
      webdev: categories.webdev ?? null,
    },
  }
}

describe('buildTaskFitModel', () => {
  it('keeps missing category blocks as unevaluated instead of rank zero', () => {
    const model = buildTaskFitModel([
      source('only-agent', {
        agent: block('agent', { kind: 'score', rank: 2, value: 0.12 }),
      }),
    ])
    const row = model.rows[0]

    expect(row.cells.document).toMatchObject({
      evaluated: false,
      rank: null,
      metric: null,
    })
    expect(formatTaskRank(row.cells.document)).toBe('Not evaluated')
    expect(model.coverage).toEqual({
      agent: 1,
      document: 0,
      search: 0,
      webdev: 0,
    })
    expect(model.rankExtent.document).toBeNull()
  })

  it('does not treat a null rank as a plotted zero', () => {
    const model = buildTaskFitModel([
      source('unranked', {
        agent: block('agent', { kind: 'score', rank: null, value: 0.04 }),
      }),
    ])
    const cell = model.rows[0].cells.agent

    expect(cell.evaluated).toBe(true)
    expect(cell.rank).toBeNull()
    expect(formatTaskRank(cell)).toBe('Not ranked')
    expect(model.rankExtent.agent).toBeNull()
  })

  it('sorts by agent rank and leaves missing ranks last', () => {
    const model = buildTaskFitModel([
      source('late', {
        agent: block('agent', { kind: 'score', rank: 20, value: -0.04 }),
        document: block('document', { kind: 'rating', rank: 1, value: 1510 }),
      }),
      source('early', {
        agent: block('agent', { kind: 'score', rank: 3, value: 0.1 }),
      }),
    ])

    expect(model.rows.map((row) => row.key)).toEqual(['early', 'late'])
    expect(model.rows[1].bestCategory).toBe('document')
    expect(
      sortTaskFitRows(model.rows, 'document').map((row) => row.key),
    ).toEqual(['late', 'early'])
  })

  it('lists best-at-task from published ranks only', () => {
    const model = buildTaskFitModel([
      source('search-lead', {
        agent: block('agent', { kind: 'score', rank: 7, value: 0.08 }),
        search: block('search', { kind: 'rating', rank: 1, value: 1257 }),
      }),
      source('no-search', {
        agent: block('agent', { kind: 'score', rank: 2, value: 0.12 }),
      }),
    ])

    expect(bestAtTask(model.rows, 'search').map((row) => row.key)).toEqual([
      'search-lead',
    ])
    expect(model.coverage.search).toBe(1)
  })
})

describe('rankStrength', () => {
  it('maps the best rank in the column to 1 and the worst to 0', () => {
    expect(rankStrength(1, { min: 1, max: 16 })).toBe(1)
    expect(rankStrength(16, { min: 1, max: 16 })).toBe(0)
    expect(rankStrength(4, { min: 1, max: 16 })).toBeCloseTo(0.5)
  })

  it('gives a lone rank full strength instead of treating it as the bottom', () => {
    expect(rankStrength(16, { min: 16, max: 16 })).toBe(1)
  })
})

describe('formatTaskMetric', () => {
  it('keeps score and rating on their own scales', () => {
    const score = {
      category: 'agent' as const,
      evaluated: true,
      metric: 0.12389,
      metricKind: 'score' as const,
      rank: 2,
      sampleSize: 10,
    }
    const rating = {
      category: 'webdev' as const,
      evaluated: true,
      metric: 1800.28,
      metricKind: 'rating' as const,
      rank: 1,
      sampleSize: 10,
    }

    expect(formatTaskMetric(score)).toMatch(/\+0\.124/)
    expect(formatTaskMetric(rating).replace(/[^\d-]/g, '')).toBe('1800')
  })
})
