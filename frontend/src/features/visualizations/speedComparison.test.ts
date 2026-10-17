import { describe, expect, it } from 'vitest'
import type { OverviewRow } from '../../api'
import { buildSpeedComparison } from './speedComparison'

function row(key: string, score: number | null, speed: number | null, latency: number | null): OverviewRow {
  return {
    model: { key, name: key, organization: 'openai', license: null, in_agent_set: true },
    aa: {
      id: key, slug: key, name: key, creator: null, release_date: null,
      intelligence_index_version: 1, intelligence_index: score, coding_index: score,
      agentic_index: null, intelligence_index_total_cost: null, cost_per_task: 1,
      pricing: { price_1m_input_tokens: 1, price_1m_output_tokens: 1,
        price_1m_cache_hit_tokens: null, price_1m_cache_write_tokens: null },
      performance: { median_output_tokens_per_second: speed,
        median_time_to_first_token_seconds: latency, median_time_to_first_answer_token_seconds: null,
        median_end_to_end_response_time_seconds: null },
      is_retained: true, last_synced_at: '2026-10-17T00:00:00Z',
    },
    categories: {
      agent: { category: 'agent', metric_kind: 'score', metric_value: score,
        metric_lower: null, metric_upper: null, metric_variance: null, sample_size: null,
        session_count: null, rank: 1, model_name: key, organization: 'openai', license: null,
        leaderboard_publish_date: null, source_key: key, matched_by_fold: false },
      document: null, search: null, webdev: null,
    },
    match: { method: 'exact_name', confidence: 1, is_manual: false,
      matched_key: key, last_matched_at: '2026-10-17T00:00:00Z' },
  }
}

describe('speed comparison', () => {
  it('keeps models that are faster or more capable on the output-speed front', () => {
    const result = buildSpeedComparison([
      row('smart-slow', 90, 10, 5),
      row('fast', 50, 100, 1),
      row('neither', 40, 20, 8),
      row('unmeasured', 80, null, 2),
    ], 'intelligence', 'output', null)
    expect(result.pareto.map((point) => point.key)).toEqual(['smart-slow', 'fast'])
    expect(result.omitted).toBe(1)
    expect(result.xDomain[0]).toBe(0)
  })

  it('treats a shorter time to first token as the better horizontal position', () => {
    const result = buildSpeedComparison([
      row('snappy', 40, 80, 1),
      row('smart-slow', 90, 20, 5),
      row('late', 30, 10, 10),
    ], 'intelligence', 'ttft', null)
    expect(result.pareto.map((point) => point.key)).toEqual(['snappy', 'smart-slow'])
    expect(result.xDomain[0]).toBeLessThan(1)
    expect(result.points.find((point) => point.key === 'snappy')?.inAttractiveQuadrant).toBe(false)
  })
})
