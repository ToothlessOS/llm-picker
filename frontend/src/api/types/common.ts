export const CATEGORIES = ['agent', 'document', 'search', 'webdev'] as const
export const SECONDARY_CATEGORIES = ['document', 'search', 'webdev'] as const
export const SOURCES = ['lmarena', 'artificial_analysis'] as const

export type Category = (typeof CATEGORIES)[number]
export type SecondaryCategory = (typeof SECONDARY_CATEGORIES)[number]
export type Source = (typeof SOURCES)[number]
export type MetricKind = 'rating' | 'score'
export type MatchMethod =
  | 'alias'
  | 'exact_key'
  | 'exact_name'
  | 'exact_slug'
  | 'harness_fold'
export type SyncStatus =
  | 'failed'
  | 'partial'
  | 'running'
  | 'skipped'
  | 'success'

export type IsoDate = string
export type IsoDateTime = string
export type Ordering<Field extends string> = Field | `-${Field}`

export interface PaginationParams {
  page?: number
  pageSize?: number
}

export interface SourceError {
  code: string
  message: string
}

export interface SourceFreshnessBase {
  configured: boolean
  last_attempt_at: IsoDateTime | null
  last_status: SyncStatus | null
  last_success_at: IsoDateTime | null
  age_seconds: number | null
  is_stale: boolean
  stale_after_seconds: number
  last_error: SourceError | null
}

export interface LMArenaFreshness extends SourceFreshnessBase {
  fields_succeeded?: Category[]
  fields_failed?: Record<string, unknown>
  dataset_revision?: string | null
}

export interface ArtificialAnalysisFreshness extends SourceFreshnessBase {
  tier?: string | null
  rate_limit?: {
    limit: number | null
    remaining: number | null
    reset_at: IsoDateTime | null
  }
  pages_fetched?: number | null
  intelligence_index_version?: number | null
}

export interface SourceFreshnessMap {
  lmarena: LMArenaFreshness
  artificial_analysis: ArtificialAnalysisFreshness
}

export interface ResponseMeta {
  generated_at: IsoDateTime
  sources: SourceFreshnessMap
}

export interface PaginatedResponse<
  Row,
  Meta extends ResponseMeta = ResponseMeta,
> {
  count: number
  next: string | null
  previous: string | null
  page_size: number
  results: Row[]
  meta: Meta
}

export type FreshnessState =
  | 'fresh'
  | 'never_refreshed'
  | 'not_configured'
  | 'refresh_failed'
  | 'stale'

export function getFreshnessState(
  freshness: SourceFreshnessBase,
): FreshnessState {
  if (!freshness.configured) return 'not_configured'
  if (freshness.last_success_at === null) return 'never_refreshed'
  if (
    freshness.last_status !== null &&
    freshness.last_status !== 'success' &&
    freshness.last_status !== 'partial'
  ) {
    return 'refresh_failed'
  }
  if (freshness.is_stale) return 'stale'
  return 'fresh'
}

export function getSourceDataUpdatedAt(
  meta: ResponseMeta,
  source: Source,
): IsoDateTime | null {
  return meta.sources[source].last_success_at
}
