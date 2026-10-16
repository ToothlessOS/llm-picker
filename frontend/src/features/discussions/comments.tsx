/**
 * The comment rendering shared by the plain thread page and the map's reader.
 *
 * Extracted from `DiscussionDetailPage` rather than rewritten, so the tests that
 * already guard the data contract — sanitized markup, the indent cap, the
 * truncation warning, the deleted-comment note — keep guarding it.
 */

import { useRef, type Ref } from 'react'
import { ArrowUpRight, TriangleAlert } from 'lucide-react'

import type {
  DiscussionComment,
  DiscussionEntityRef,
  DiscussionThreadDetail,
} from '../../api'
import { formatNumber, formatRelativeTime } from '../../app/format'
import { useHighlight } from './highlight'

/** Deep threads indent off-screen, so the indent stops growing past this level. */
export const MAX_INDENT = 12

export function EntityChips({ entities }: { entities: DiscussionEntityRef[] }) {
  if (entities.length === 0) return null
  return (
    <span className="entity-chips">
      {entities.map((entity) => (
        <span
          className={`entity-chip entity-chip--${entity.kind}`}
          key={entity.slug}
          title={`${entity.matched_text} · ${entity.mentions} mention(s)`}
        >
          {entity.label}
        </span>
      ))}
    </span>
  )
}

export interface CommentNodeProps {
  comment: DiscussionComment
  /** The active search term. Occurrences in the body are marked. */
  search?: string
  /**
   * The indent to draw at. Defaults to the comment's own depth; the reader passes
   * a depth *relative to its focus*, so a deep focus does not shove its replies
   * off the right edge.
   */
  indent?: number
  /** Being read right now — thickened border, in both panes. */
  isActive?: boolean
  /** The block the reader is scoped to. */
  isFocus?: boolean
  /** For scroll-into-view and the reader's `IntersectionObserver`. */
  nodeRef?: Ref<HTMLElement>
}

/**
 * One comment.
 *
 * Rendered from `text_html`, which the backend **sanitized at ingest** against a
 * tag and attribute allowlist. That is why this is the one place in the frontend
 * that uses `dangerouslySetInnerHTML`: re-escaping it would show markup to the
 * reader, and sanitizing again here would be a second implementation to keep
 * correct. The sanitizer's own tests cover the adversarial cases.
 *
 * The search marks are applied to the rendered result by a `TreeWalker` — see
 * `highlight.ts` for why that is the safe mechanism and a string replace is not.
 *
 * `text_plain` is what everything *except* the body should use — a title, a
 * tooltip, an aria-label — because reading HTML as text shows tags.
 */
export function CommentNode({
  comment,
  search = '',
  indent,
  isActive = false,
  isFocus = false,
  nodeRef,
}: CommentNodeProps) {
  const bodyRef = useRef<HTMLDivElement | null>(null)
  useHighlight(bodyRef, search, comment.text_html)

  const className = [
    'discussion-comment',
    comment.is_deleted ? 'discussion-comment--deleted' : '',
    comment.is_dead ? 'discussion-comment--dead' : '',
    isFocus ? 'is-focus' : '',
    isActive ? 'is-active' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <article
      className={className}
      data-hn-id={comment.hn_id}
      // The anchor for `?comment=` and for scrolling the reader to a block.
      id={`comment-${comment.hn_id}`}
      ref={nodeRef}
      style={
        {
          '--depth': Math.min(indent ?? comment.depth, MAX_INDENT),
        } as React.CSSProperties
      }
    >
      <header className="discussion-comment__meta">
        <span className="discussion-comment__author">
          {comment.author ?? 'deleted'}
        </span>
        {comment.posted_at ? (
          <span className="muted">{formatRelativeTime(comment.posted_at)}</span>
        ) : null}
        {comment.points !== null ? (
          <span className="muted">{formatNumber(comment.points, 0)} points</span>
        ) : null}
        {comment.children_count > 0 ? (
          <span className="muted">
            {formatNumber(comment.children_count, 0)} repl
            {comment.children_count === 1 ? 'y' : 'ies'}
          </span>
        ) : null}
        {comment.is_dead ? <span className="muted">flagged</span> : null}
        <EntityChips entities={comment.entities} />
      </header>

      {comment.is_deleted && !comment.text_html ? (
        <p className="muted discussion-comment__body">
          The author deleted this comment. Its replies are kept.
        </p>
      ) : (
        <div
          className="discussion-comment__body"
          dangerouslySetInnerHTML={{ __html: comment.text_html }}
          ref={bodyRef}
        />
      )}
    </article>
  )
}

/**
 * The "we only kept part of this" warning.
 *
 * Its own component because two very different layouts need it — the plain
 * thread page and the map's reader — and a warning that says something different
 * depending on where you are reading it would be worse than no warning.
 */
export function TruncationWarning({ thread }: { thread: DiscussionThreadDetail }) {
  if (!thread.tree_truncated) return null

  return (
    <p className="callout callout--warning" role="note">
      <TriangleAlert aria-hidden="true" size={16} />
      Only {formatNumber(thread.comments_stored, 0)} of{' '}
      {formatNumber(thread.num_comments, 0)} comments are stored — this
      discussion was truncated by the ingest cap.
    </p>
  )
}

export function ThreadSummary({ thread }: { thread: DiscussionThreadDetail }) {
  return (
    <div className="discussion-summary">
      <dl className="stat-strip">
        <div>
          <dt>Points</dt>
          <dd>{formatNumber(thread.points, 0)}</dd>
        </div>
        <div>
          <dt>Comments</dt>
          <dd>
            {formatNumber(thread.comments_stored, 0)}
            {thread.num_comments !== null &&
            thread.num_comments !== thread.comments_stored ? (
              <span className="muted"> / {formatNumber(thread.num_comments, 0)}</span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Depth</dt>
          <dd>{formatNumber(thread.max_depth, 0)}</dd>
        </div>
        <div>
          <dt>Posted</dt>
          <dd>{formatRelativeTime(thread.posted_at)}</dd>
        </div>
      </dl>

      <p className="discussion-summary__links">
        {thread.author ? (
          <span className="muted">submitted by {thread.author}</span>
        ) : null}
        <a href={thread.hn_url} rel="noreferrer" target="_blank">
          Open on Hacker News
          <ArrowUpRight aria-hidden="true" size={15} />
        </a>
        {thread.url ? (
          <a href={thread.url} rel="noreferrer" target="_blank">
            {thread.domain ?? 'Original link'}
            <ArrowUpRight aria-hidden="true" size={15} />
          </a>
        ) : null}
        <EntityChips entities={thread.entities} />
      </p>

      <TruncationWarning thread={thread} />
    </div>
  )
}
