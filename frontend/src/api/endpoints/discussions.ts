import { apiClient, type ApiRequestOptions } from '../client'
import { commaSeparated, type QueryParams } from '../query'
import type {
  Ordering,
  PaginationParams,
} from '../types/common'
import type {
  DiscussionDetailResponse,
  DiscussionEntitiesResponse,
  DiscussionListResponse,
  EntityKind,
} from '../types/discussions'

export type DiscussionOrderingField =
  | 'rank_score'
  | 'points'
  | 'num_comments'
  | 'comments_stored'
  | 'posted_at'
  | 'fetched_at'
  | 'title'
  | 'domain'

export interface DiscussionParams extends PaginationParams {
  search?: string
  entity?: readonly string[]
  kind?: readonly EntityKind[]
  minPoints?: number
  maxPoints?: number
  minComments?: number
  maxComments?: number
  /** `YYYY-MM-DD`, inclusive of the whole day at the upper bound. */
  postedAfter?: string
  postedBefore?: string
  ordering?: readonly Ordering<DiscussionOrderingField>[]
}

export interface DiscussionDetailParams {
  /** Server-side trim, so a shallow first view costs less to paint. */
  maxDepth?: number
  search?: string
  entity?: string
}

export function serializeDiscussionParams(params: DiscussionParams): QueryParams {
  return {
    search: params.search,
    entity: commaSeparated(params.entity),
    kind: commaSeparated(params.kind),
    min_points: params.minPoints,
    max_points: params.maxPoints,
    min_comments: params.minComments,
    max_comments: params.maxComments,
    posted_after: params.postedAfter,
    posted_before: params.postedBefore,
    ordering: commaSeparated(params.ordering),
    page: params.page,
    page_size: params.pageSize,
  }
}

export function getDiscussions(
  params: DiscussionParams = {},
  options?: ApiRequestOptions,
): Promise<DiscussionListResponse> {
  return apiClient.get('discussions/', serializeDiscussionParams(params), options)
}

export function getDiscussion(
  hnId: number | string,
  params: DiscussionDetailParams = {},
  options?: ApiRequestOptions,
): Promise<DiscussionDetailResponse> {
  return apiClient.get(
    `discussions/${hnId}/`,
    {
      max_depth: params.maxDepth,
      search: params.search,
      entity: params.entity,
    },
    options,
  )
}

/**
 * The filter vocabulary.
 *
 * Unpaginated and deliberately *not* derived from `/overview/`: that returns
 * LMArena organization strings, which is a different vocabulary from these
 * reviewed entity slugs.
 */
export function getDiscussionEntities(
  options?: ApiRequestOptions,
): Promise<DiscussionEntitiesResponse> {
  return apiClient.get('discussions/entities/', {}, options)
}

/** The backend's default page size for this endpoint — the draft's "top 10". */
export const DISCUSSION_PAGE_SIZE = 10
