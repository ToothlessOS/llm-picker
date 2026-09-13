import { apiClient, type ApiRequestOptions } from '../client'
import { commaSeparated, type QueryParams } from '../query'
import type {
  Ordering,
  PaginatedResponse,
  PaginationParams,
  ResponseMeta,
  SecondaryCategory,
} from '../types/common'
import type { OverviewRow } from '../types/models'

export type OverviewOrderingField =
  | 'rank'
  | 'model_name'
  | 'organization'
  | 'metric_value'
  | 'sample_size'
  | 'session_count'
  | 'leaderboard_publish_date'
  | 'aa_intelligence_index'
  | 'aa_cost_per_task'
  | 'aa_price_1m_input_tokens'
  | 'aa_intelligence_index_total_cost'
  | 'aa_coding_index'
  | 'aa_agentic_index'
  | 'aa_price_1m_output_tokens'
  | 'aa_price_1m_cache_hit_tokens'
  | 'aa_price_1m_cache_write_tokens'
  | 'aa_median_output_tokens_per_second'
  | 'aa_median_time_to_first_token_seconds'
  | 'aa_median_time_to_first_answer_token_seconds'
  | 'aa_median_end_to_end_response_time_seconds'

export interface OverviewParams extends PaginationParams {
  search?: string
  organization?: string
  rankMin?: number
  rankMax?: number
  metricMin?: number
  metricMax?: number
  sampleMin?: number
  sampleMax?: number
  includeCategories?: readonly SecondaryCategory[] | 'all' | 'none'
  ordering?: readonly Ordering<OverviewOrderingField>[]
}

export interface OverviewMeta extends ResponseMeta {
  categories_included: SecondaryCategory[]
}

export type OverviewResponse = PaginatedResponse<OverviewRow, OverviewMeta>

export function serializeOverviewParams(params: OverviewParams): QueryParams {
  const categories = Array.isArray(params.includeCategories)
    ? params.includeCategories.length
      ? params.includeCategories.join(',')
      : 'none'
    : params.includeCategories

  return {
    search: params.search,
    organization: params.organization,
    rank_min: params.rankMin,
    rank_max: params.rankMax,
    metric_min: params.metricMin,
    metric_max: params.metricMax,
    sample_min: params.sampleMin,
    sample_max: params.sampleMax,
    include_categories: categories,
    ordering: commaSeparated(params.ordering),
    page: params.page,
    page_size: params.pageSize,
  }
}

export function getOverview(
  params: OverviewParams = {},
  options?: ApiRequestOptions,
): Promise<OverviewResponse> {
  return apiClient.get('overview/', serializeOverviewParams(params), options)
}
