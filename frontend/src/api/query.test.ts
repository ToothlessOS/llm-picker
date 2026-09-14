import { describe, expect, it } from 'vitest'

import { serializeArtificialAnalysisParams } from './endpoints/artificialAnalysis'
import { serializeCategoryParams } from './endpoints/categories'
import { serializeOverviewParams } from './endpoints/overview'
import { serializeUnmatchedParams } from './endpoints/unmatched'
import { buildQueryString } from './query'

describe('buildQueryString', () => {
  it('keeps false and zero while omitting empty values', () => {
    const result = buildQueryString({
      current: false,
      page: 0,
      search: '  claude  ',
      ignored: undefined,
      blank: '   ',
      emptyList: [],
      ordering: ['rank', '-metric_value'],
    })

    expect(result).toBe(
      'current=false&page=0&search=claude&ordering=rank%2C-metric_value',
    )
  })

  it('rejects non-finite numeric values before a request is sent', () => {
    expect(() => buildQueryString({ metric: Number.NaN })).toThrow(TypeError)
  })
})

describe('endpoint parameter serialization', () => {
  it('maps overview filters and ordering to the backend names', () => {
    expect(
      serializeOverviewParams({
        rankMin: 2,
        metricMax: 0.2,
        includeCategories: ['document', 'webdev'],
        ordering: ['-aa_intelligence_index', 'rank'],
        pageSize: 75,
      }),
    ).toMatchObject({
      rank_min: 2,
      metric_max: 0.2,
      include_categories: 'document,webdev',
      ordering: '-aa_intelligence_index,rank',
      page_size: 75,
    })
  })

  it('serializes an empty category selection as none', () => {
    expect(
      serializeOverviewParams({ includeCategories: [] }).include_categories,
    ).toBe('none')
  })

  it('keeps category-specific filter names distinct from overview', () => {
    expect(
      serializeCategoryParams({
        inAgentSet: false,
        minMetric: 1_000,
        minSampleSize: 50,
        scope: 'all',
      }),
    ).toMatchObject({
      in_agent_set: false,
      min_metric: 1_000,
      min_sample_size: 50,
      scope: 'all',
    })
  })

  it('expands Artificial Analysis metric ranges', () => {
    expect(
      serializeArtificialAnalysisParams({
        retained: false,
        intelligenceIndexVersion: 4.3,
        metricRanges: {
          cost_per_task: { min: 0.01, max: 0.1 },
          intelligence_index: { min: 40 },
        },
      }),
    ).toMatchObject({
      retained: false,
      intelligence_index_version: 4.3,
      min_cost_per_task: 0.01,
      max_cost_per_task: 0.1,
      min_intelligence_index: 40,
    })
  })

  it('maps unmatched filters without dropping false', () => {
    expect(
      serializeUnmatchedParams({
        source: 'lmarena',
        category: 'agent',
        current: false,
        ordering: ['-last_seen_at'],
      }),
    ).toMatchObject({
      source: 'lmarena',
      category: 'agent',
      current: false,
      ordering: '-last_seen_at',
    })
  })
})
