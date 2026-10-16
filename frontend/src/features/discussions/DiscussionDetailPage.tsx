import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useParams } from 'react-router-dom'

import { getDiscussion } from '../../api'
import { PageHeader } from '../../components/PageHeader'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'
import { CommentNode, ThreadSummary } from './comments'

/**
 * One thread, read top to bottom.
 *
 * The comments are a **flat list rendered with an indent derived from `depth`**,
 * ordered by `path` on the server — which is pre-order, so a comment is always
 * followed by its replies and then the next sibling. That is deliberately *not* a
 * tree chart: `/discussions/map` draws the tree, and this page stays as the view
 * where the stored data — the ordering, the sanitized markup, the per-comment
 * tags, the truncation — is checkable by eye.
 */
export function DiscussionDetailPage() {
  const { hnId = '' } = useParams<{ hnId: string }>()
  const location = useLocation()
  const query = useQuery({
    queryKey: ['discussion', hnId],
    queryFn: ({ signal }) => getDiscussion(hnId, {}, { signal }),
    staleTime: 300_000,
  })

  const thread = query.data?.thread
  const comments = query.data?.comments ?? []

  return (
    <main className="page">
      <p className="breadcrumb">
        <Link to={{ pathname: '/discussions', search: location.search }}>
          ← All discussions
        </Link>
      </p>

      <PageHeader
        description={
          thread
            ? `${thread.comments_stored.toLocaleString()} comments stored · ${
                thread.entities.length
              } entities mentioned`
            : 'Loading a Hacker News discussion.'
        }
        isFetching={query.isFetching && !query.isPending}
        title={thread?.title ?? 'Discussion'}
      />

      {thread ? (
        <p className="page-note">
          <Link to={{ pathname: '/discussions/map', search: `?thread=${thread.hn_id}` }}>
            Open the discussion map →
          </Link>
        </p>
      ) : null}

      {query.isPending ? <LoadingState label="Loading discussion" /> : null}
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : null}

      {thread ? (
        <>
          <ThreadSummary thread={thread} />

          {comments.length === 0 ? (
            <p className="state-message" role="status">
              <strong>No comments stored for this thread.</strong>
              <span>
                Its tree has not been fetched yet, or every comment was filtered
                out. The hourly job retries.
              </span>
            </p>
          ) : (
            <section aria-label="Comments" className="discussion-comments">
              {comments.map((comment) => (
                <CommentNode comment={comment} key={comment.hn_id} />
              ))}
            </section>
          )}
        </>
      ) : null}
    </main>
  )
}
