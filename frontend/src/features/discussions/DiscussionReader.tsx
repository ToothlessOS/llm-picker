import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowUpRight, ChevronDown, ChevronRight } from 'lucide-react'

import type { DiscussionComment, DiscussionThreadDetail } from '../../api'
import { formatNumber } from '../../app/format'
import { CommentNode, TruncationWarning } from './comments'
import { ancestorIds, subtreeIds, type DiscussionTree } from './discussionTree'

/**
 * How many comments the reader will hold in the DOM at once.
 *
 * A 1,532-comment thread rendered in full is ~7,600 elements and about 180ms of
 * first paint; at 200 it is ~25ms. The control says how many are left, so the
 * cap never silently hides anything.
 */
const READER_PAGE = 200

export interface DiscussionReaderProps {
  thread: DiscussionThreadDetail
  tree: DiscussionTree
  /** Resolved from `?comment=`. `null` means the whole thread. */
  focusId: number | null
  /** The raw `?comment=` value, when it resolved to nothing — a stale link. */
  staleFocus: string | null
  collapsed: ReadonlySet<number>
  search: string
  /**
   * The comment being read, as reported back through `onReadingChange`.
   *
   * It comes *back* into the reader as well as going out to the map, because
   * rule 5 is about both panes at once: the same comment wears the same
   * thickened border wherever it appears.
   */
  readingId: number | null
  /** Drop the focus and go back to the whole thread. */
  onClearFocus: () => void
  onToggle: (id: number) => void
  onReadingChange: (id: number | null) => void
}

/**
 * The discussion, in reading order.
 *
 * **The reader is the truth of the thread; the map is a summary of it.** That one
 * sentence decides both behaviours below: the reader shows every comment in the
 * focus subtree (rule 1 — "like the regular HN page"), and it deliberately does
 * *not* inherit the map's automatic collapsing, because a reader that hid
 * comments on its own would be lying about the thread. Only the user's explicit
 * collapses cross over, so the two panes never disagree about what was asked for.
 */
export function DiscussionReader({
  thread,
  tree,
  focusId,
  staleFocus,
  collapsed,
  search,
  readingId,
  onClearFocus,
  onToggle,
  onReadingChange,
}: DiscussionReaderProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [shown, setShown] = useState(READER_PAGE)

  const focusDepth =
    focusId === null ? 0 : (tree.nodes.get(focusId)?.renderDepth ?? 0)

  /** Every comment in scope, minus anything under one the user collapsed. */
  const reading = useMemo(() => {
    const ids = focusId === null ? tree.order : subtreeIds(tree, focusId)
    return ids.filter((id) => {
      if (id === focusId) return false
      return !ancestorIds(tree, id).some((ancestor) => collapsed.has(ancestor))
    })
  }, [tree, focusId, collapsed])

  // A new focus, a new search: start the reader at the top of the page again,
  // rather than leaving the user 400 comments into a different subtree. Adjusted
  // during render rather than in an effect, so the reset is never one frame late —
  // the same pattern `SearchField` uses to resync with the URL.
  const resetKey = `${focusId ?? 'all'}|${search}`
  const [lastResetKey, setLastResetKey] = useState(resetKey)
  if (lastResetKey !== resetKey) {
    setLastResetKey(resetKey)
    setShown(READER_PAGE)
  }

  // Choosing a branch starts its replies from the top. The focus itself needs no
  // scrolling to — it is pinned above this region, not inside it.
  useEffect(() => {
    const container = containerRef.current
    if (container) container.scrollTop = 0
  }, [focusId])

  /**
   * Follow the reader's scroll position.
   *
   * The observer's root margin is what makes this a *reading* position rather
   * than a visibility test: the comment crossing the top quarter of the pane is
   * the one being read, not every comment on screen. Scrolling the reader only
   * highlights the map — it never scrolls it, which is what keeps the two panes
   * from chasing each other.
   */
  useEffect(() => {
    const root = containerRef.current
    if (!root || reading.length === 0) return
    if (typeof IntersectionObserver === 'undefined') return

    // Notes which of the observed articles are inside the reading band, so the
    // topmost one can be picked in DOM order rather than in callback order.
    const seen = new WeakMap<Element, boolean>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) seen.set(entry.target, entry.isIntersecting)

        for (const article of root.querySelectorAll<HTMLElement>('article[data-hn-id]')) {
          if (!seen.get(article)) continue
          onReadingChange(Number(article.dataset.hnId))
          return
        }
        onReadingChange(null)
      },
      { root, rootMargin: '-8% 0px -70% 0px' },
    )

    for (const article of root.querySelectorAll('article[data-hn-id]')) {
      observer.observe(article)
    }
    return () => observer.disconnect()
    // `reading` is memoized, so this re-subscribes when the rendered set changes
    // rather than on every unrelated render.
  }, [reading, onReadingChange])

  const focusComment = focusId === null ? null : tree.nodes.get(focusId)?.comment
  const page = reading.slice(0, shown)
  const remaining = reading.length - page.length

  return (
    <section className="reader" aria-label="Reader">
      {/*
        First, and outside the scrolling region, so it stays where it is. Inside
        the region it would scroll away while reading and — once a branch is
        pinned above the region — it would end up *below* the branch, which is
        the wrong way round: the thread's provenance is a property of the whole
        pane, not of whatever is currently selected in it.
      */}
      <ReaderDetails thread={thread} />

      {/*
        The focused block is pinned *above* the scrolling region rather than
        sticking inside it.

        It started out as `position: sticky`, which is what "always appears at
        the top of the reader" sounds like — but sticky means the element floats
        over its own scroll layer, so the replies slid *underneath* the pinned
        comment and were painted behind it. That is sticky working as designed,
        and it is not what a reader wants to see. As a sibling region the two
        cannot overlap at all: the pinned comment holds its place and the replies
        scroll below it in the space that is left.
      */}
      {focusComment ? (
        <div className="reader__pinned">
          <p className="reader__focus-kicker">
            Reading this branch
            {/* "Back to thread" rather than "Whole thread": the button leaves the
                branch you are in, and naming the *action* says that, where naming
                the destination read as a label for the pane. */}
            <button
              className="reader__focus-reset"
              onClick={onClearFocus}
              type="button"
            >
              <ArrowLeft aria-hidden="true" size={13} />
              Back to thread
            </button>
          </p>
          <div className="reader__pinned-body">
            <CommentNode comment={focusComment} indent={0} isFocus search={search} />
          </div>
        </div>
      ) : null}

      <div className="reader__scroll" ref={containerRef}>
        {staleFocus !== null ? (
          <p className="state-message" role="status">
            <strong>That comment is not in the current data.</strong>
            <span>
              Showing the whole thread instead. A link shared before the last
              refresh can point at a comment that has since gone.
            </span>
          </p>
        ) : null}

        {/* How many comments are in scope. Truncation is *not* mentioned here —
            the summary above already warns about it, and saying it twice in one
            column reads as two separate problems. */}
        <p className="reader__status" role="status">
          {focusComment
            ? `${formatNumber(reading.length, 0)} ${
                reading.length === 1 ? 'reply' : 'replies'
              } to this comment`
            : `${formatNumber(reading.length, 0)} comments`}
        </p>

        {page.map((id) => {
          const comment = tree.nodes.get(id)?.comment
          if (comment === undefined) return null
          return (
            <ReaderRow
              collapsed={collapsed.has(id)}
              comment={comment}
              focusDepth={focusDepth}
              isActive={readingId === id}
              key={id}
              onToggle={() => onToggle(id)}
              search={search}
              subtreeSize={tree.nodes.get(id)?.subtreeSize ?? 1}
            />
          )
        })}

        {remaining > 0 ? (
          <button
            className="reader__more"
            onClick={() => setShown((current) => current + READER_PAGE)}
            type="button"
          >
            Show {formatNumber(Math.min(remaining, READER_PAGE), 0)} more of{' '}
            {formatNumber(remaining, 0)} remaining
          </button>
        ) : null}

        {reading.length === 0 && focusComment === null ? (
          <p className="state-message" role="status">
            <strong>No comments stored for this thread.</strong>
            <span>
              Its tree has not been fetched yet, or every comment was filtered
              out. The hourly job retries.
            </span>
          </p>
        ) : null}

        {/* The truncation warning is not repeated here — `ThreadSummary` above
            already carries it, and saying it twice in one column reads as two
            separate problems. */}
      </div>
    </section>
  )
}

/**
 * The thread's provenance, and nothing else.
 *
 * Deliberately much thinner than the shared `ThreadSummary`, because on this page
 * almost all of that panel is already on screen twice: the points, comment count
 * and age are in the rail row of the selected thread and again in the toolbar's
 * count line, and the thread's entity tags are the map's own legend, listed there
 * with the colours they are drawn in and the number of comments behind each.
 * Repeating them here cost about 150px of reading space on a busy thread and
 * pushed the first comment below the fold.
 *
 * What is left is what exists nowhere else on the page: who submitted it, the two
 * outbound links, and the truncation warning.
 */
function ReaderDetails({ thread }: { thread: DiscussionThreadDetail }) {
  return (
    <section aria-labelledby="reader-details-heading" className="reader__details">
      <h2 className="reader__details-heading" id="reader-details-heading">
        Details
      </h2>
      <p className="reader__links">
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
      </p>
      <TruncationWarning thread={thread} />
    </section>
  )
}

function ReaderRow({
  comment,
  collapsed,
  focusDepth,
  subtreeSize,
  search,
  isActive,
  onToggle,
}: {
  comment: DiscussionComment
  collapsed: boolean
  focusDepth: number
  subtreeSize: number
  search: string
  isActive: boolean
  onToggle: () => void
}) {
  const hidden = collapsed ? subtreeSize - 1 : 0

  return (
    <>
      <CommentNode
        comment={comment}
        indent={Math.max(0, comment.depth - focusDepth)}
        isActive={isActive}
        search={search}
      />
      {subtreeSize > 1 ? (
        <button
          aria-expanded={!collapsed}
          className="reader__toggle"
          onClick={onToggle}
          style={
            { '--depth': Math.min(Math.max(0, comment.depth - focusDepth), 12) } as React.CSSProperties
          }
          type="button"
        >
          {collapsed ? (
            <>
              <ChevronRight aria-hidden="true" size={14} />
              Show {formatNumber(hidden, 0)}{' '}
              {hidden === 1 ? 'reply' : 'replies'}
            </>
          ) : (
            <>
              <ChevronDown aria-hidden="true" size={14} />
              Hide replies
            </>
          )}
        </button>
      ) : null}
    </>
  )
}
