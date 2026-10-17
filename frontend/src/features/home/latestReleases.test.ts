import { describe, expect, it } from 'vitest'
import type { OverviewRow } from '../../api'
import { latestReleases } from './latestReleases'

function row(name: string, date: string | null, creator = 'OpenAI'): OverviewRow {
  return {
    model: { key: name, name, organization: 'openai', license: null, in_agent_set: true },
    aa: {
      id: name, slug: name, name, creator: { id: creator, name: creator },
      release_date: date, intelligence_index_version: 1, intelligence_index: 1,
      coding_index: null, agentic_index: null, intelligence_index_total_cost: null,
      cost_per_task: 1,
      pricing: { price_1m_input_tokens: 1, price_1m_output_tokens: 1, price_1m_cache_hit_tokens: null, price_1m_cache_write_tokens: null },
      performance: { median_output_tokens_per_second: null, median_time_to_first_token_seconds: null, median_time_to_first_answer_token_seconds: null, median_end_to_end_response_time_seconds: null },
      is_retained: true, last_synced_at: '2026-10-17T00:00:00Z',
    },
    categories: {
      agent: { category: 'agent', metric_kind: 'score', metric_value: 0, metric_lower: null, metric_upper: null, metric_variance: null, sample_size: null, session_count: null, rank: 1, model_name: name, organization: 'openai', license: null, leaderboard_publish_date: null, source_key: name, matched_by_fold: false },
      document: null, search: null, webdev: null,
    },
    match: { method: 'exact_name', confidence: 1, is_manual: false, matched_key: name, last_matched_at: '2026-10-17T00:00:00Z' },
  }
}

describe('latestReleases', () => {
  it('keeps the three newest dated models', () => {
    const notes = latestReleases([
      row('Old', '2026-01-01', 'Meta'),
      row('Newest', '2026-10-16', 'OpenAI'),
      row('Undated', null, 'Google'),
      row('Middle', '2026-08-02', 'Anthropic'),
      row('Recent', '2026-09-12', 'Google'),
    ])
    expect(notes.map((note) => note.name)).toEqual(['Newest', 'Recent', 'Middle'])
    expect(notes[0]?.creator).toBe('OpenAI')
  })
})
