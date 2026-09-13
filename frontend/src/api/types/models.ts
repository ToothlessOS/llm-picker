import type {
  Category,
  IsoDate,
  IsoDateTime,
  MatchMethod,
  MetricKind,
  SecondaryCategory,
} from './common'

export const AA_METRIC_FIELDS = [
  'intelligence_index',
  'coding_index',
  'agentic_index',
  'intelligence_index_total_cost',
  'cost_per_task',
  'price_1m_input_tokens',
  'price_1m_output_tokens',
  'price_1m_cache_hit_tokens',
  'price_1m_cache_write_tokens',
  'median_output_tokens_per_second',
  'median_time_to_first_token_seconds',
  'median_time_to_first_answer_token_seconds',
  'median_end_to_end_response_time_seconds',
] as const

export type AAMetricField = (typeof AA_METRIC_FIELDS)[number]

export interface ModelIdentity {
  key: string
  name: string
  organization: string | null
  license: string | null
  in_agent_set: boolean
}

export interface CategoryBlock {
  category: Category
  metric_kind: MetricKind
  metric_value: number | null
  metric_lower: number | null
  metric_upper: number | null
  metric_variance: number | null
  sample_size: number | null
  session_count: number | null
  rank: number | null
  model_name: string
  organization: string | null
  license: string | null
  leaderboard_publish_date: IsoDate | null
  source_key: string
  matched_by_fold: boolean
}

export interface CategoryBlocks {
  agent: CategoryBlock
  document: CategoryBlock | null
  search: CategoryBlock | null
  webdev: CategoryBlock | null
}

export interface ArtificialAnalysisModel {
  id: string
  slug: string
  name: string
  creator: { id: string; name: string } | null
  release_date: IsoDate | null
  intelligence_index_version: number | null
  intelligence_index: number | null
  coding_index: number | null
  agentic_index: number | null
  intelligence_index_total_cost: number | null
  cost_per_task: number | null
  pricing: {
    price_1m_input_tokens: number | null
    price_1m_output_tokens: number | null
    price_1m_cache_hit_tokens: number | null
    price_1m_cache_write_tokens: number | null
  }
  performance: {
    median_output_tokens_per_second: number | null
    median_time_to_first_token_seconds: number | null
    median_time_to_first_answer_token_seconds: number | null
    median_end_to_end_response_time_seconds: number | null
  }
  is_retained: boolean
  last_synced_at: IsoDateTime
}

export interface ModelMatch {
  method: MatchMethod
  confidence: number
  is_manual: boolean
  matched_key: string
  last_matched_at: IsoDateTime
}

export interface OverviewRow {
  model: ModelIdentity
  categories: CategoryBlocks
  aa: ArtificialAnalysisModel
  match: ModelMatch
}

export interface CategoryModelIdentity extends ModelIdentity {
  agent_key: string | null
}

export interface CategoryRow {
  model: CategoryModelIdentity
  category: CategoryBlock
  matched_by_fold: boolean
}

export interface ArtificialAnalysisRow {
  aa: ArtificialAnalysisModel
  matched_model: {
    key: string
    name: string
    organization: string | null
    match_method: MatchMethod
    confidence: number
    agent: CategoryBlock
  } | null
}

export interface CategorySourceProvenance {
  source_key: string
  source_name: string
  matched_by_fold: boolean
  last_synced_at: IsoDateTime
}

export interface ModelDetailResponse extends OverviewRow {
  provenance: {
    agent_key: string
    aa_match_method: MatchMethod | null
    aa_match_is_manual: boolean
    category_sources: Partial<
      Record<SecondaryCategory, CategorySourceProvenance>
    >
    lmarena_last_synced_at: IsoDateTime
  }
}
