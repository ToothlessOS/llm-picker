import type { Category, IsoDateTime, Source } from './common'

export type UnmatchedReason =
  | 'ambiguous_match'
  | 'duplicate_model_name'
  | 'missing_identity'
  | 'no_aa_match'
  | 'no_lmarena_match'
  | 'not_in_agent_set'
  | 'validation_failed'

export interface UnmatchedRecord {
  source: Source
  category: Category | null
  reason: UnmatchedReason
  model_key: string
  model_name: string | null
  organization: string | null
  occurrences: number
  is_current: boolean
  first_seen_at: IsoDateTime
  last_seen_at: IsoDateTime
  detail: Record<string, unknown>
}
