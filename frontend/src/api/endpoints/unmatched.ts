import { apiClient, type ApiRequestOptions } from '../client'
import { commaSeparated, type QueryParams } from '../query'
import type {
  Category,
  Ordering,
  PaginatedResponse,
  PaginationParams,
  Source,
} from '../types/common'
import type { UnmatchedRecord } from '../types/unmatched'

export type UnmatchedOrderingField =
  | 'source'
  | 'category'
  | 'reason'
  | 'model_key'
  | 'model_name'
  | 'organization'
  | 'occurrences'
  | 'first_seen_at'
  | 'last_seen_at'

export interface UnmatchedParams extends PaginationParams {
  source?: Source
  category?: Category
  reason?: string
  current?: boolean
  search?: string
  ordering?: readonly Ordering<UnmatchedOrderingField>[]
}

export type UnmatchedResponse = PaginatedResponse<UnmatchedRecord>

export function serializeUnmatchedParams(params: UnmatchedParams): QueryParams {
  return {
    source: params.source,
    category: params.category,
    reason: params.reason,
    current: params.current,
    search: params.search,
    ordering: commaSeparated(params.ordering),
    page: params.page,
    page_size: params.pageSize,
  }
}

export function getUnmatched(
  params: UnmatchedParams = {},
  options?: ApiRequestOptions,
): Promise<UnmatchedResponse> {
  return apiClient.get('unmatched/', serializeUnmatchedParams(params), options)
}
