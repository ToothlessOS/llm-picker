import type {
  IsoDateTime,
  PaginatedResponse,
  ResponseMeta,
  SourceFreshnessBase,
} from './common'

/**
 * The two axes the provider filter offers.
 *
 * There is deliberately no third for model variants: tagging free text with an
 * exact model variant is a much stronger claim than tagging it with a vendor, and
 * the backend does not make it.
 */
export const ENTITY_KINDS = ['vendor', 'service'] as const
export type EntityKind = (typeof ENTITY_KINDS)[number]

/** One entity a thread or comment mentions, with the alias that fired. */
export interface DiscussionEntityRef {
  slug: string
  label: string
  kind: EntityKind
  /** The vendor a service rolls up to, so a client can group without a lookup. */
  vendor: string | null
  /** The verbatim string that matched — the review record for the tag. */
  matched_text: string
  match_mode: string
  mentions: number
}

export interface DiscussionThreadRow {
  hn_id: number
  title: string
  url: string | null
  domain: string | null
  author: string | null
  points: number | null
  /** What Hacker News reports. `null` means unreported, never zero. */
  num_comments: number | null
  /**
   * What we kept. Read it *beside* `num_comments`: the gap is how much of the
   * discussion is missing, and `tree_truncated` says whether the ingest cap
   * caused it.
   */
  comments_stored: number
  max_depth: number
  tree_truncated: boolean
  rank_score: number | null
  /** The relevance terms that put this thread in the bank. */
  keywords: string[]
  posted_at: IsoDateTime
  fetched_at: IsoDateTime | null
  last_synced_at: IsoDateTime
  hn_url: string
  entities: DiscussionEntityRef[]
  /** Present only when a search was supplied, so absent never means "no matches". */
  matched_comment_count: number | null
}

export interface DiscussionThreadDetail
  extends Omit<DiscussionThreadRow, 'matched_comment_count'> {
  window_days: number
}

/**
 * One node of a discussion, in a **flat** list ordered by `path`.
 *
 * `depth` and `parent_hn_id` are everything needed to build a tree; the first
 * frontend renders an indented list from them without one. The flat shape is what
 * keeps two things unambiguous that nesting would hide: whether a childless node
 * is childless or was cut by the ingest cap (`children_count` counts stored
 * children, `tree_truncated` says whether any were cut), and whether a missing
 * parent means a deleted one.
 */
export interface DiscussionComment {
  hn_id: number
  parent_hn_id: number | null
  depth: number
  sibling_index: number
  /** Zero-padded sibling-index chain; a string sort of it is pre-order. */
  path: string
  children_count: number
  author: string | null
  points: number | null
  /** Sanitized at ingest against an allowlist. Safe to render as HTML. */
  text_html: string
  /** Whitespace-collapsed. Use this for anything that is not HTML. */
  text_plain: string
  is_deleted: boolean
  is_dead: boolean
  posted_at: IsoDateTime | null
  hn_url: string
  entities: DiscussionEntityRef[]
}

export interface DiscussionCounts {
  threads: number
  comments: number
  tags: number
  entities: number
}

/**
 * Hacker News freshness.
 *
 * Lives under `meta.discussions`, **not** in `meta.sources` — that block describes
 * the model rows a response carries and is typed as exactly two sources.
 */
export interface DiscussionFreshness extends SourceFreshnessBase {
  counts: DiscussionCounts
  window_days: number
  default_page_size: number
  top_n: number
  enabled: boolean
}

export interface DiscussionMeta extends ResponseMeta {
  discussions: DiscussionFreshness
}

export interface DiscussionDetailMeta extends DiscussionMeta {
  max_depth: number | null
  search: string | null
  entity: string | null
  comments_returned: number
}

export type DiscussionListResponse = PaginatedResponse<
  DiscussionThreadRow,
  DiscussionMeta
>

export interface DiscussionDetailResponse {
  thread: DiscussionThreadDetail
  comments: DiscussionComment[]
  meta: DiscussionDetailMeta
}

/** One row of the filter vocabulary. */
export interface DiscussionEntity {
  slug: string
  label: string
  kind: EntityKind
  vendor: string | null
  /** The LMArena organization spelling, when one exists — the bridge to the models. */
  lmarena_organization: string | null
  /** What actually tags this entity, so a thin filter can be told from a typo. */
  aliases: string[]
  /** Threads tagged **directly**; a click on this row produces the roll-up. */
  thread_count: number
  note: string | null
}

export interface DiscussionEntitiesResponse {
  results: DiscussionEntity[]
  meta: DiscussionMeta & { kinds: EntityKind[] }
}

export function isDiscussionExpired(freshness: DiscussionFreshness): boolean {
  return freshness.last_success_at === null
}
