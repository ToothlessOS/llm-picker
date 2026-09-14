import type {
  Category,
  IsoDate,
  IsoDateTime,
  MatchMethod,
  MetricKind,
  ResponseMeta,
  Source,
  SourceFreshnessMap,
  SyncStatus,
} from './common'

export interface CategorySummary {
  category: Category
  metric_kind: MetricKind | null
  entry_count: number
  in_agent_set_count: number
  rank_min: number | null
  rank_max: number | null
  latest_publish_date: IsoDate | null
}

export interface CategoryIndexMeta extends ResponseMeta {
  primary_category: 'agent'
  matched_agent_models: number
}

export interface CategoryIndexResponse {
  results: CategorySummary[]
  meta: CategoryIndexMeta
}

export interface SyncRun {
  id: number
  source: Source
  status: SyncStatus
  triggered_by: string | null
  dry_run: boolean
  started_at: IsoDateTime
  finished_at: IsoDateTime | null
  duration_ms: number | null
  records_seen: number
  records_created: number
  records_updated: number
  records_unchanged: number
  records_deactivated: number
  records_failed: number
  records_deduplicated: number
  anomalies_recorded: number
  error_code: string | null
  error_message: string | null
}

export interface MetadataCounts {
  lmarena_entries: number
  lmarena_agent_entries: number
  complete_agent_entries: number
  aa_models: number
  aa_models_retained: number
  matches: number
  unmatched_records: number
}

export interface MetadataResponse {
  sources: SourceFreshnessMap
  counts: MetadataCounts
  categories: CategorySummary[]
  matching: Record<string, number> & Partial<Record<MatchMethod, number>>
  recent_runs: SyncRun[]
  config: {
    harness_fold_enabled: boolean
    stale_after_seconds: number
  }
  attribution: {
    artificial_analysis: string
    lmarena: string
  }
  meta: ResponseMeta
}
