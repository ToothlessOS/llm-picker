"""The discussion endpoints.

Three GET-only views, subclassing the same `LeaderboardView` base as every other
endpoint so pagination, the `meta` envelope and the error shapes cannot drift.

The property this module must preserve is the one `views.py` documents for the
model endpoints: **no request can reach the network**, because there is no code
path from here to one. These modules import no client, no service and no matcher
-- entity matching ran at *ingest*, so a tag is a stored row and the filter is a
join rather than an inference performed per request. `test_api_no_network.py`
enforces it twice over: by grepping the read path's source for forbidden imports,
and by making every outbound seam raise.

`meta.discussions` carries Hacker News freshness. It is deliberately **not** added
to `meta.sources`, which describes the model rows a response is carrying and which
the frontend types as exactly two sources -- reporting discussions there would put
their freshness on `/overview/` and widen a contract for no gain.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from rest_framework.exceptions import APIException
from rest_framework.response import Response

from ..constants import (
    DEFAULT_DISCUSSION_ORDERING,
    DISCUSSION_ORDERING,
    EntityKind,
    hn_config,
)
from . import discussion_selectors as selectors
from . import discussion_serializers as serializers
from .errors import InvalidParameter, StructuredDetail
from .pagination import DiscussionPagination
from .params import get_choice, get_int, get_list, get_ordering, get_text
from .views import LeaderboardView

#: `/discussions/{hn_id}/` accepts a `max_depth` up to this. Bounded so a typo
#: cannot ask for a range the ingest cap could never have produced.
MAX_DEPTH_CEILING = 64


def discussion_meta() -> dict:
    """The `discussions` block carried by every discussion response.

    Built on `selectors.source_freshness`, so the never-refreshed / failing /
    simply-old trichotomy is the same one every other source reports. The
    threshold is Hacker News's own rather than the model sources': the job runs
    hourly, so two hours tolerates one missed run, where the twice-daily model
    refresh needs fourteen. Sharing one number would either raise a false alarm
    here or hide a real one there.
    """
    return selectors.discussion_freshness(
        stale_after_seconds=hn_config().stale_after_seconds
    )


class NotFound(StructuredDetail, APIException):
    """404 for a thread that is not in the bank.

    Shaped like `ModelIncomplete`: it names what was asked for and explains
    itself, so a stale link says *why* rather than reporting a generic failure.
    The likely cause is worth stating outright -- a thread ages out of the bank
    after the retention window and is deleted, so a link older than that is
    expected to expire.
    """

    status_code = 404
    default_code = "not_found"

    def __init__(self, value: str | int, *, window_days: int):
        super().__init__(
            {
                "error": "not_found",
                "hn_id": value,
                "message": (
                    f"No discussion {value!r} is stored. Threads are retained for "
                    f"{window_days} days and then pruned, so a link older than that "
                    "is expected to have expired."
                ),
            }
        )


def _day_start(value: date | None) -> datetime | None:
    """A `YYYY-MM-DD` lower bound, widened to the start of that UTC day."""
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _day_end(value: date | None) -> datetime | None:
    """An upper bound widened to the *end* of that day.

    Without this, `posted_before=2026-10-01` would mean "before midnight on the
    1st" and silently exclude the whole of the day a reader asked for -- the
    opposite of what they meant.
    """
    if value is None:
        return None
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _get_date(request, name: str) -> date | None:
    raw = get_text(request, name)
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise InvalidParameter(
            name, f"{name} must be a date (YYYY-MM-DD), got {raw!r}."
        ) from None


class DiscussionListView(LeaderboardView):
    """`GET /discussions/` -- the retained bank, ranked.

    Defaults to the draft's top ten. The whole bank is one `?page_size=` away,
    which is what makes the filters worth offering: over a bank of ten the
    Provider dropdown would return almost nothing and read as broken.
    """

    pagination_class = DiscussionPagination

    def get(self, request) -> Response:
        search = get_text(request, "search")
        # The entity list is validated against the live vocabulary, so an unknown
        # slug is a 400 naming the alternatives rather than an empty result that
        # reads as "no threads discuss this".
        entities = get_list(request, "entity", allowed=selectors.entity_slugs())
        kinds = get_list(request, "kind", allowed=EntityKind.values)

        queryset = selectors.apply_thread_filters(
            selectors.threads(),
            search=search,
            entities=entities,
            kinds=kinds,
            min_points=get_int(request, "min_points", minimum=0),
            max_points=get_int(request, "max_points", minimum=0),
            min_comments=get_int(request, "min_comments", minimum=0),
            max_comments=get_int(request, "max_comments", minimum=0),
            posted_after=_day_start(_get_date(request, "posted_after")),
            posted_before=_day_end(_get_date(request, "posted_before")),
        )
        queryset = selectors.matching_comment_counts(queryset, search=search)
        queryset = queryset.order_by(
            *get_ordering(
                request,
                allowed=DISCUSSION_ORDERING,
                default=DEFAULT_DISCUSSION_ORDERING,
            )
        )

        page = self.paginate(queryset)
        tags = selectors.thread_tags([thread.pk for thread in page])
        rows = [
            serializers.thread_row(thread, tags=tags.get(thread.pk, ()))
            for thread in page
        ]

        return self.finish(rows, extra_meta={"discussions": discussion_meta()})


class DiscussionDetailView(LeaderboardView):
    """`GET /discussions/{hn_id}/` -- one thread and its comments.

    Comments come back as a **flat list ordered by `path`**, in a single response.
    Every node carries `depth` and `parent_hn_id`, which is everything a consumer
    needs to build a tree -- or, as the first frontend does, to render an indented
    list without one.

    Not paginated, because the ingest cap already bounds the response: at most
    `LEADERBOARD_HN_MAX_STORED_COMMENTS` nodes, so the largest possible payload is
    a few hundred kilobytes for a view whose whole purpose is to draw them.
    """

    def get(self, request, hn_id: str) -> Response:
        window_days = hn_config().window_days
        try:
            identifier = int(hn_id)
        except (TypeError, ValueError):
            raise NotFound(hn_id, window_days=window_days) from None

        thread = selectors.get_thread(identifier)
        if thread is None:
            raise NotFound(identifier, window_days=window_days)

        max_depth = get_int(request, "max_depth", minimum=0, maximum=MAX_DEPTH_CEILING)
        search = get_text(request, "search")
        entity = get_choice(request, "entity", selectors.entity_slugs(), default=None)

        comments = list(
            selectors.thread_comments(
                thread, max_depth=max_depth, search=search, entity=entity
            )
        )
        children = selectors.comment_counts(thread)
        tags = selectors.comment_tags([comment.pk for comment in comments])
        title_tags = selectors.thread_tags([thread.pk]).get(thread.pk, ())

        return Response(
            {
                "thread": serializers.thread_detail(thread, tags=title_tags),
                "comments": [
                    serializers.comment_row(
                        comment,
                        children_count=children.get(comment.hn_id, 0),
                        tags=tags.get(comment.pk, ()),
                    )
                    for comment in comments
                ],
                "meta": self.meta(
                    {
                        "discussions": discussion_meta(),
                        "max_depth": max_depth,
                        "search": search,
                        "entity": entity,
                        "comments_returned": len(comments),
                    }
                ),
            }
        )


class DiscussionEntityIndexView(LeaderboardView):
    """`GET /discussions/entities/` -- the filter vocabulary.

    A fixed-size index, so it is not paginated -- but it still carries `meta`, so
    the frontend's freshness badge behaves identically on every call.

    One call gives the dropdowns their options from real data. Reusing
    `AppShell`'s provider query instead would return LMArena organization
    *strings*, which is a different vocabulary: an entity is a reviewed row with
    aliases and a vendor, while an organization is verbatim upstream text.

    `thread_count` counts threads tagged **directly**. A vendor's total therefore
    excludes threads that only name one of its services, because a click on it
    produces the *roll-up*; reporting the rolled-up total here would make the
    number disagree with the rows behind it.
    """

    def get(self, request) -> Response:
        rows = serializers.entity_index_rows(
            selectors.entity_index(),
            counts=selectors.entity_thread_counts(),
            aliases=selectors.aliases_by_entity(),
        )
        return Response(
            {
                "results": rows,
                "meta": self.meta(
                    {"discussions": discussion_meta(), "kinds": list(EntityKind.values)}
                ),
            }
        )


__all__ = [
    "DiscussionDetailView",
    "DiscussionEntityIndexView",
    "DiscussionListView",
    "MAX_DEPTH_CEILING",
    "NotFound",
    "discussion_meta",
]
