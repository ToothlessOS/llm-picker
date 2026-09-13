import { apiClient, type ApiRequestOptions } from '../client'
import { commaSeparated, type QueryParams } from '../query'
import type {
  Ordering,
  PaginatedResponse,
  PaginationParams,
  ResponseMeta,
} from '../types/common'
import {
  AA_METRIC_FIELDS,
  type AAMetricField,
  type ArtificialAnalysisRow,
} from '../types/models'

export type ArtificialAnalysisOrderingField =
  | AAMetricField
  | 'creator'
  | 'last_synced_at'
  | 'name'
  | 'release_date'
  | 'slug'

export interface NumericRange {
  min?: number
  max?: number
}

export interface ArtificialAnalysisParams extends PaginationParams {
  retained?: boolean
  matched?: boolean
  search?: string
  creator?: string
  intelligenceIndexVersion?: number
  releaseDateAfter?: string
  releaseDateBefore?: string
  metricRanges?: Partial<Record<AAMetricField, NumericRange>>
  ordering?: readonly Ordering<ArtificialAnalysisOrderingField>[]
}

export interface ArtificialAnalysisMeta extends ResponseMeta {
  retained: boolean | null
  metric_fields: AAMetricField[]
}

export type ArtificialAnalysisResponse = PaginatedResponse<
  ArtificialAnalysisRow,
  ArtificialAnalysisMeta
>

export function serializeArtificialAnalysisParams(
  params: ArtificialAnalysisParams,
): QueryParams {
  const query: Record<string, boolean | number | string | undefined> = {
    retained: params.retained,
    matched: params.matched,
    search: params.search,
    creator: params.creator,
    intelligence_index_version: params.intelligenceIndexVersion,
    release_date_after: params.releaseDateAfter,
    release_date_before: params.releaseDateBefore,
    ordering: commaSeparated(params.ordering),
    page: params.page,
    page_size: params.pageSize,
  }

  for (const field of AA_METRIC_FIELDS) {
    const range = params.metricRanges?.[field]
    if (range?.min !== undefined) query[`min_${field}`] = range.min
    if (range?.max !== undefined) query[`max_${field}`] = range.max
  }

  return query
}

export function getArtificialAnalysis(
  params: ArtificialAnalysisParams = {},
  options?: ApiRequestOptions,
): Promise<ArtificialAnalysisResponse> {
  return apiClient.get(
    'artificial-analysis/',
    serializeArtificialAnalysisParams(params),
    options,
  )
}
