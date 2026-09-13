import { apiClient, type ApiRequestOptions } from '../client'
import { commaSeparated, type QueryParams } from '../query'
import type {
  Category,
  MetricKind,
  Ordering,
  PaginatedResponse,
  PaginationParams,
  ResponseMeta,
} from '../types/common'
import type { CategoryRow } from '../types/models'
import type { CategoryIndexResponse } from '../types/metadata'

export type CategoryOrderingField =
  | 'rank'
  | 'model_name'
  | 'organization'
  | 'metric_value'
  | 'sample_size'
  | 'session_count'
  | 'leaderboard_publish_date'

export interface CategoryParams extends PaginationParams {
  inAgentSet?: boolean
  scope?: 'all'
  matched?: boolean
  search?: string
  organization?: string
  rankMin?: number
  rankMax?: number
  minMetric?: number
  maxMetric?: number
  minSampleSize?: number
  maxSampleSize?: number
  ordering?: readonly Ordering<CategoryOrderingField>[]
}

export interface CategoryMeta extends ResponseMeta {
  category: Category
  metric_kind: MetricKind | null
  in_agent_set: boolean | null
  scope: 'all' | null
}

export type CategoryResponse = PaginatedResponse<CategoryRow, CategoryMeta>

export function serializeCategoryParams(params: CategoryParams): QueryParams {
  return {
    in_agent_set: params.inAgentSet,
    scope: params.scope,
    matched: params.matched,
    search: params.search,
    organization: params.organization,
    rank_min: params.rankMin,
    rank_max: params.rankMax,
    min_metric: params.minMetric,
    max_metric: params.maxMetric,
    min_sample_size: params.minSampleSize,
    max_sample_size: params.maxSampleSize,
    ordering: commaSeparated(params.ordering),
    page: params.page,
    page_size: params.pageSize,
  }
}

export function getCategories(
  options?: ApiRequestOptions,
): Promise<CategoryIndexResponse> {
  return apiClient.get('categories/', {}, options)
}

export function getCategory(
  category: Category,
  params: CategoryParams = {},
  options?: ApiRequestOptions,
): Promise<CategoryResponse> {
  return apiClient.get(
    `categories/${encodeURIComponent(category)}/`,
    serializeCategoryParams(params),
    options,
  )
}
