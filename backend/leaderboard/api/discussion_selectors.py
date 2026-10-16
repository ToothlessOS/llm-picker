"""Query construction for the discussion endpoints.

The same contract as `selectors.py`: every queryset a discussion view executes is
built here, so the read path stays a pure database query and a view never reaches
for a matcher, a client or a service. Entity matching happened at *ingest* -- a
tag is a stored row -- which is what lets the filter be a join rather than an
inference performed per request.

Two query shapes need care, and both are about joins multiplying rows:

* `search` reaches through the comment relation, so a thread with twelve matching
  comments would otherwise be returned twelve times and its `count` would be
  twelve. Every such filter ends in `.distinct()`.
* The provider roll-up matches a thread tagged with an entity **or** with any
  service belonging to it. That is a second join on the same relation, so it is
  one `Q` with two branches rather than two filters -- chaining two `filter()`
  calls would require a single tag to satisfy both.

`kind` is deliberately **not** rolled up, unlike `entity`. It answers "what kind of
thing is the tag that fired", which is a question about the row; `entity` answers
"is this thread about Anthropic", which a service tag also settles. Making both
roll up would leave no way to ask the narrower question.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Sequence

from django.db.models import Count, Q, QuerySet

from ..constants import (
    DEFAULT_DISCUSSION_PAGE_SIZE,
    Source,
    hn_config,
)
from ..models import DiscussionTag, HNComment, HNThread, ProviderEntity
from . import selectors as model_selectors

# --------------------------------------------------------------------------- #
# Base querysets
# --------------------------------------------------------------------------- #


def threads() -> QuerySet[HNThread]:
    """Every stored thread.

    No `is_active` filter, and that is deliberate rather than an omission: for this
    source membership *is* the served set. A thread leaves the bank by aging out
    and being deleted, which is monotonic, so there is no hidden population to
    filter away.
    """
    return HNThread.objects.all()


def thread_tags(thread_ids: Iterable[int]) -> dict[int, list[DiscussionTag]]:
    """`{thread_id: [tag, ...]}` for a page of threads, in one query.

    One query rather than one per row: a page of fifty threads would otherwise be
    fifty-one queries, the same problem `category_blocks` exists to avoid.
    """
    ids = list(thread_ids)
    if not ids:
        return {}
    grouped: dict[int, list[DiscussionTag]] = {}
    for tag in DiscussionTag.objects.filter(thread_id__in=ids).select_related("entity"):
        grouped.setdefault(tag.thread_id, []).append(tag)
    return grouped


def comment_counts(thread: HNThread) -> dict[int | None, int]:
    """`{parent_hn_id: number of stored children}` for one thread.

    Computed as one aggregate rather than per-comment, and it counts only what is
    **stored** -- so a node whose replies were cut by the ingest cap reports zero
    children, which is a fact about our copy rather than about Hacker News. That
    is why the thread also carries `tree_truncated`: it is what tells a reader the
    difference between "nobody replied" and "we did not keep the replies".
    """
    rows = (
        HNComment.objects.filter(thread=thread)
        .values("parent_hn_id")
        .annotate(total=Count("id"))
    )
    return {row["parent_hn_id"]: row["total"] for row in rows}


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


def apply_thread_filters(
    queryset: QuerySet[HNThread],
    *,
    search: str | None = None,
    entities: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    min_points: int | None = None,
    max_points: int | None = None,
    min_comments: int | None = None,
    max_comments: int | None = None,
    posted_after: datetime | None = None,
    posted_before: datetime | None = None,
) -> QuerySet[HNThread]:
    """Every filter `/discussions/` accepts, applied in one place."""
    if search:
        # `distinct` is not optional: the comment join multiplies rows, so without
        # it a thread with twelve matching comments is returned twelve times and
        # the paginated `count` reports twelve.
        queryset = queryset.filter(
            Q(title__icontains=search) | Q(comments__text_plain__icontains=search)
        ).distinct()

    if entities:
        # One `Q` with two branches, not two chained filters: chaining would
        # demand a single tag satisfying both, which no row can.
        queryset = queryset.filter(
            Q(tags__entity__slug__in=entities) | Q(tags__entity__vendor__slug__in=entities)
        ).distinct()

    if kinds:
        queryset = queryset.filter(tags__entity__kind__in=kinds).distinct()

    if min_points is not None:
        queryset = queryset.filter(points__gte=min_points)
    if max_points is not None:
        queryset = queryset.filter(points__lte=max_points)
    if min_comments is not None:
        queryset = queryset.filter(num_comments__gte=min_comments)
    if max_comments is not None:
        queryset = queryset.filter(num_comments__lte=max_comments)
    if posted_after is not None:
        queryset = queryset.filter(posted_at__gte=posted_after)
    if posted_before is not None:
        queryset = queryset.filter(posted_at__lte=posted_before)

    return queryset


def matching_comment_counts(queryset: QuerySet[HNThread], *, search: str | None):
    """Annotate `matched_comment_count`, or leave the queryset alone.

    Only added when a search is active: without one the number is meaningless (it
    would be every comment), and the annotation is not free.
    """
    if not search:
        return queryset
    return queryset.annotate(
        matched_comment_count=Count(
            "comments",
            filter=Q(comments__text_plain__icontains=search),
            distinct=True,
        )
    )


# --------------------------------------------------------------------------- #
# Detail
# --------------------------------------------------------------------------- #


def thread_comments(
    thread: HNThread,
    *,
    max_depth: int | None = None,
    search: str | None = None,
    entity: str | None = None,
) -> QuerySet[HNComment]:
    """One thread's comments, in the order a reader reads them.

    Ordered by `path`, which is a zero-padded sibling index chain -- so a plain
    string sort reproduces pre-order traversal: a comment, then its replies, then
    the next sibling. The frontend's indented list and any future tree both depend
    on that being true, and it is pinned by a test.
    """
    queryset = HNComment.objects.filter(thread=thread)
    if max_depth is not None:
        queryset = queryset.filter(depth__lte=max_depth)
    if search:
        queryset = queryset.filter(text_plain__icontains=search)
    if entity:
        queryset = queryset.filter(tags__entity__slug=entity)
    return queryset.order_by("path", "pk")


def comment_tags(comment_ids: Iterable[int]) -> dict[int, list[DiscussionTag]]:
    """`{comment_id: [tag, ...]}` for one thread's page of comments."""
    ids = list(comment_ids)
    if not ids:
        return {}
    grouped: dict[int, list[DiscussionTag]] = {}
    for tag in DiscussionTag.objects.filter(comment_id__in=ids).select_related("entity"):
        grouped.setdefault(tag.comment_id, []).append(tag)
    return grouped


def get_thread(hn_id: int) -> HNThread | None:
    return HNThread.objects.filter(hn_id=hn_id).first()


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #


def entity_slugs(*, active_only: bool = True) -> list[str]:
    """Every slug `/discussions/?entity=` accepts, for param validation."""
    queryset = ProviderEntity.objects.all()
    if active_only:
        queryset = queryset.filter(is_active=True)
    return list(queryset.values_list("slug", flat=True))


def entity_thread_counts() -> dict[int, int]:
    """`{entity_id: number of tagged threads}`, in one aggregate.

    Counts threads tagged **directly**. A vendor's own count therefore excludes the
    threads that only name one of its services -- which is why the filter, not this
    number, is what implements the roll-up. Reporting a roll-up total here would
    make the number disagree with the list a click on it produces.
    """
    rows = (
        DiscussionTag.objects.values("entity_id")
        .annotate(total=Count("thread_id", distinct=True))
    )
    return {row["entity_id"]: row["total"] for row in rows}


def entity_index() -> list[ProviderEntity]:
    return list(
        ProviderEntity.objects.filter(is_active=True)
        .select_related("vendor")
        .order_by("kind", "label")
    )


def aliases_by_entity() -> dict[int, list[str]]:
    """`{entity_id: [alias_text, ...]}`, so the index shows what actually tags."""
    grouped: dict[int, list[str]] = {}
    for entity_id, alias_text in (
        ProviderEntity.objects.filter(is_active=True)
        .values_list("aliases__entity_id", "aliases__alias_text")
        .order_by("aliases__alias_text")
    ):
        if entity_id is None:
            continue
        grouped.setdefault(entity_id, []).append(alias_text)
    return grouped


# --------------------------------------------------------------------------- #
# Freshness and counts
# --------------------------------------------------------------------------- #


def discussion_counts() -> dict[str, int]:
    return {
        "threads": HNThread.objects.count(),
        "comments": HNComment.objects.count(),
        "tags": DiscussionTag.objects.count(),
        "entities": ProviderEntity.objects.filter(is_active=True).count(),
    }


def discussion_freshness(*, stale_after_seconds: int) -> dict[str, Any]:
    """The `meta.discussions` block.

    Deliberately **not** part of `meta.sources`. That block is the per-source
    freshness of the rows a response is carrying, and it is typed on the frontend
    as `{lmarena, artificial_analysis}` -- reporting Hacker News there would put
    discussion freshness on `/overview/` and widen a contract for no gain.

    Built on `source_freshness`, so the never-refreshed / failing / simply-old
    trichotomy is the same one every other source reports.
    """
    info = model_selectors.source_freshness(
        Source.HACKERNEWS.value, stale_after_seconds=stale_after_seconds
    )
    config = hn_config()
    info["counts"] = discussion_counts()
    info["window_days"] = config.window_days
    info["default_page_size"] = DEFAULT_DISCUSSION_PAGE_SIZE
    info["top_n"] = DEFAULT_DISCUSSION_PAGE_SIZE
    info["enabled"] = config.enabled
    return info


__all__ = [
    "aliases_by_entity",
    "apply_thread_filters",
    "comment_counts",
    "comment_tags",
    "discussion_counts",
    "discussion_freshness",
    "entity_index",
    "entity_slugs",
    "entity_thread_counts",
    "get_thread",
    "matching_comment_counts",
    "thread_comments",
    "thread_tags",
    "threads",
]
