import { describe, expect, it } from 'vitest'
import type { OverviewRow } from '../../api'
import {
  buildPerformanceComparison, keysInScatterBounds, toggleComparedModel,
} from './performanceComparison'

function row(key: string, cost: number | null, intelligence: number | null,
  coding: number | null, agent: number | null, organization = 'openai'): OverviewRow {
  return {
    model: { key, name: key, organization, license: null, in_agent_set: true },
    aa: {
      id: key, slug: key, name: key, creator: null, release_date: null,
      intelligence_index_version: 1, intelligence_index: intelligence, coding_index: coding,
      agentic_index: null, intelligence_index_total_cost: null, cost_per_task: cost,
      pricing: { price_1m_input_tokens: cost, price_1m_output_tokens: cost,
        price_1m_cache_hit_tokens: null, price_1m_cache_write_tokens: null },
      performance: { median_output_tokens_per_second: null,
        median_time_to_first_token_seconds: null, median_time_to_first_answer_token_seconds: null,
        median_end_to_end_response_time_seconds: null },
      is_retained: true, last_synced_at: '2026-10-17T00:00:00Z',
    },
    categories: {
      agent: { category: 'agent', metric_kind: 'score', metric_value: agent,
        metric_lower: null, metric_upper: null, metric_variance: null, sample_size: null,
        session_count: null, rank: 1, model_name: key, organization, license: null,
        leaderboard_publish_date: null, source_key: key, matched_by_fold: false },
      document: null, search: null, webdev: null,
    },
    match: { method: 'exact_name', confidence: 1, is_manual: false,
      matched_key: key, last_matched_at: '2026-10-17T00:00:00Z' },
  }
}

describe('coordinated performance comparison', () => {
  it('uses actual scores and independently computes the three Pareto fronts', () => {
    const result = buildPerformanceComparison([
      row('a', 1, 80, 30, -0.4), row('b', 2, 70, 90, 0.2),
      row('c', 3, null, null, -0.2),
    ], 'task', 'log', null)
    expect(result.models.intelligence.pareto.map((point) => point.key)).toEqual(['a'])
    expect(result.models.coding.pareto.map((point) => point.key)).toEqual(['a', 'b'])
    expect(result.models.agent.points.map((point) => point.intelligence)).toEqual([-0.4, 0.2, -0.2])
    expect(result.models.agent.pareto.map((point) => point.key)).toEqual(['a', 'b'])
    expect(result.models.coding.omitted).toBe(1)
    expect(result.models.agent.omitted).toBe(0)
    expect(result.xDomain[0]).toBeLessThan(1)
    expect(result.xDomain[1]).toBeGreaterThan(3)
  })

  it('includes zero cost only on linear axes and never fills missing costs', () => {
    const rows = [row('free', 0, 30, 50, 0), row('missing', null, 40, 20, -0.5), row('paid', 1, 50, 60, 0.3)]
    expect(buildPerformanceComparison(rows, 'input', 'log', null).models.agent.points.map((point) => point.key)).toEqual(['paid'])
    expect(buildPerformanceComparison(rows, 'input', 'linear', null).models.agent.points.map((point) => point.key)).toEqual(['free', 'paid'])
  })

  it('recomputes the cohort frontier after a provider filter', () => {
    const rows = [row('dominant', 1, 90, 80, 0.5, 'anthropic'), row('other', 2, 60, 50, 0.1)]
    const all = buildPerformanceComparison(rows, 'task', 'log', null)
    const filtered = buildPerformanceComparison(rows, 'task', 'log', 'openai')
    expect(all.models.intelligence.pareto.map((point) => point.key)).toEqual(['dominant'])
    expect(filtered.models.intelligence.pareto.map((point) => point.key)).toEqual(['other'])
  })

  it('brushes inclusive bounds using cost and the selected score, including negative scores', () => {
    const result = buildPerformanceComparison([row('a', 1, 80, 30, -0.4), row('b', 2, 70, 90, 0.2)], 'task', 'log', null)
    expect(keysInScatterBounds(result.models.agent, { x: [1, 2], y: [-0.4, 0] })).toEqual(['a'])
    expect(keysInScatterBounds(result.models.agent, { x: [3, 4], y: [-1, 1] })).toEqual([])
  })

  it('keeps existing pins when the three-model limit is reached', () => {
    expect(toggleComparedModel(['a', 'b', 'c'], 'd')).toEqual(['a', 'b', 'c'])
    expect(toggleComparedModel(['a', 'b', 'c'], 'b')).toEqual(['a', 'c'])
  })
})
