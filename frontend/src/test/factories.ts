import type {
  DiscussionComment,
  DiscussionEntityRef,
  DiscussionThreadRow,
  SourceFreshnessBase,
} from '../api'

/**
 * A valid `meta.sources` entry, for tests that build a whole response body.
 *
 * Exists because `sources` is typed as exactly two sources, so an empty object is
 * not assignable — and the alternative in a test is either a cast (which hides a
 * genuine shape change) or twenty lines of boilerplate per file. Nothing here
 * asserts anything; a test that cares about freshness should override the field it
 * cares about.
 */
export function sourceFreshness(
  overrides: Partial<SourceFreshnessBase> = {},
): SourceFreshnessBase {
  return {
    configured: true,
    last_attempt_at: '2026-10-16T11:00:00Z',
    last_status: 'success',
    last_success_at: '2026-10-16T11:00:00Z',
    age_seconds: 3600,
    is_stale: false,
    stale_after_seconds: 50400,
    last_error: null,
    ...overrides,
  }
}

/** The two model sources, since `meta.sources` holds exactly those. */
export function sourceFreshnessMap() {
  return {
    lmarena: sourceFreshness(),
    artificial_analysis: sourceFreshness(),
  }
}

/** One entity mention on a comment or thread. Defaults to a Claude service tag. */
export function entityRef(
  overrides: Partial<DiscussionEntityRef> = {},
): DiscussionEntityRef {
  return {
    slug: 'claude',
    label: 'Claude',
    kind: 'service',
    vendor: 'anthropic',
    matched_text: 'Claude',
    match_mode: 'word',
    mentions: 1,
    ...overrides,
  }
}

/** A vendor tag — no `vendor` of its own, which is what makes it a roll-up target. */
export function vendorRef(slug: string, label = slug): DiscussionEntityRef {
  return entityRef({ slug, label, kind: 'vendor', vendor: null })
}

/**
 * One comment.
 *
 * `text_plain` defaults to something short enough to land at the floor of the
 * height scale, so a test that cares about height has to say so explicitly —
 * which is the point of a default.
 */
export function discussionComment(
  overrides: Partial<DiscussionComment> = {},
): DiscussionComment {
  const hn_id = overrides.hn_id ?? 2001
  return {
    hn_id,
    parent_hn_id: null,
    depth: 0,
    sibling_index: 0,
    path: '000000',
    children_count: 0,
    author: 'alice',
    points: null,
    text_html: '<p>A comment</p>',
    text_plain: 'A comment',
    is_deleted: false,
    is_dead: false,
    posted_at: '2026-10-16T09:30:00Z',
    hn_url: `https://news.ycombinator.com/item?id=${hn_id}`,
    entities: [],
    ...overrides,
  }
}

export interface CommentSpec {
  id: number
  text?: string
  entities?: DiscussionEntityRef[]
  children?: CommentSpec[]
}

/**
 * Flatten a nested spec into the shape the API returns: a **flat, pre-order**
 * array whose `path` is the zero-padded chain of sibling indices, and whose
 * `depth`, `parent_hn_id` and `sibling_index` all agree with it.
 *
 * Building fixtures through the same ordering the backend guarantees is
 * deliberate — a test that handed the module a shuffled array would be testing a
 * response the API cannot produce.
 */
export function commentTree(
  specs: readonly CommentSpec[],
  parent: { id: number; depth: number; path: string } | null = null,
): DiscussionComment[] {
  const out: DiscussionComment[] = []

  specs.forEach((spec, index) => {
    const path = parent
      ? `${parent.path}.${String(index).padStart(6, '0')}`
      : String(index).padStart(6, '0')
    const depth = parent ? parent.depth + 1 : 0

    out.push(
      discussionComment({
        hn_id: spec.id,
        parent_hn_id: parent ? parent.id : null,
        depth,
        sibling_index: index,
        path,
        // `CommentSpec.text` is the *plain* text; the HTML is only ever a wrapper
        // around it, so a test asserting on the body can use either.
        text_html: `<p>${spec.text ?? 'A comment'}</p>`,
        text_plain: spec.text ?? 'A comment',
        children_count: spec.children?.length ?? 0,
        entities: spec.entities ?? [],
      }),
    )

    if (spec.children) {
      out.push(...commentTree(spec.children, { id: spec.id, depth, path }))
    }
  })

  return out
}

/** One row of the thread rail. */
export function discussionThreadRow(
  overrides: Partial<DiscussionThreadRow> = {},
): DiscussionThreadRow {
  const hn_id = overrides.hn_id ?? 1001
  return {
    hn_id,
    title: 'Claude 5 is out',
    url: 'https://anthropic.com/news',
    domain: 'anthropic.com',
    author: 'poster',
    points: 900,
    num_comments: 120,
    comments_stored: 120,
    max_depth: 2,
    tree_truncated: false,
    rank_score: 1020,
    keywords: ['claude'],
    posted_at: '2026-10-16T08:00:00Z',
    fetched_at: '2026-10-16T11:00:00Z',
    last_synced_at: '2026-10-16T11:00:00Z',
    hn_url: `https://news.ycombinator.com/item?id=${hn_id}`,
    entities: [],
    matched_comment_count: null,
    ...overrides,
  }
}
