"""The read-only endpoints.

Every view is a GET-only `APIView`. That choice is deliberate over
`ReadOnlyModelViewSet`: the response shapes here are compositions across three
tables plus a derived match record, so generic-view machinery would be either
bypassed or fought at every step. A 405 comes free from `http_method_names`.

The single most important property of this module is what is *absent* from its
imports: no client, no transport, no `datasets`. A request cannot make an
external call because there is no code path to one -- `tests/test_api_no_network.py`
enforces that by making every transport raise and asserting the endpoints still
answer.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from ..constants import (
    AA_NUMERIC_FIELDS,
    AA_ORDERING,
    CATEGORIES,
    CATEGORY_ORDERING,
    DEFAULT_AA_ORDERING,
    DEFAULT_CATEGORY_ORDERING,
    DEFAULT_OVERVIEW_ORDERING,
    DEFAULT_UNMATCHED_ORDERING,
    INTERSECTED_CATEGORIES,
    OVERVIEW_ORDERING,
    PRIMARY_CATEGORY,
    Source,
    UNMATCHED_ORDERING,
    UnmatchedReason,
    stale_after_seconds,
)
from ..models import LLMModel, ModelMatch, SyncRun, UnmatchedRecord
from . import params, selectors, serializers
from .errors import InvalidParameter, ModelIncomplete, UnknownValue
from .pagination import LeaderboardPagination

#: How many recent runs `/metadata/` echoes back.
RECENT_RUNS = 5


class LeaderboardView(APIView):
    http_method_names = ["get", "head", "options"]
    pagination_class = LeaderboardPagination

    # -- pagination plumbing ------------------------------------------------ #
    #
    # DRF puts `paginator` / `paginate_queryset` / `get_paginated_response` on
    # `GenericAPIView`. We subclass plain `APIView` deliberately -- nothing here
    # serializes a queryset, and the response shapes are compositions across
    # three tables plus a derived match record -- so those three members are
    # restated below rather than dragged in with the rest of the generic
    # machinery. Pagination is the one piece of it we actually want.

    @property
    def paginator(self) -> LeaderboardPagination | None:
        if not hasattr(self, "_paginator"):
            klass = self.pagination_class
            self._paginator = klass() if klass is not None else None
        return self._paginator

    def paginate_queryset(self, queryset) -> list[Any] | None:
        paginator = self.paginator
        if paginator is None:
            return None
        return paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data) -> Response:
        return self.paginator.get_paginated_response(data)

    # -- shared plumbing --------------------------------------------------- #

    def meta(self, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """`generated_at` plus the freshness block, on every page."""
        payload = selectors.freshness_summary(stale_after_seconds=stale_after_seconds())
        if extra:
            payload.update(extra)
        return payload

    def finish(
        self,
        rows: list[dict[str, Any]],
        *,
        extra_meta: Mapping[str, Any] | None = None,
    ) -> Response:
        self.paginator.extra_meta = self.meta(extra_meta)
        return self.get_paginated_response(rows)

    def paginate(self, queryset) -> list[Any]:
        page = self.paginate_queryset(queryset)
        if page is None:
            # Only reachable if `pagination_class` is set to None, which would
            # make the `meta` contract silently disappear. Fail loudly instead.
            raise ImproperlyConfigured("Leaderboard endpoints require pagination.")
        return page


# --------------------------------------------------------------------------- #
# 1. /overview/
# --------------------------------------------------------------------------- #


class OverviewView(LeaderboardView):
    """Joined, visualization-ready list -- **complete entries only**.

    No `matched` or `has_aa` parameter exists here, because both are invariantly
    true: a row without an AA match is not returned at all. The escape hatches
    for the excluded rows are `/categories/{category}/?matched=false`,
    `/artificial-analysis/?matched=false` and `/unmatched/`.
    """

    def get(self, request) -> Response:
        entries = selectors.complete_agent_entries()
        entries = selectors.apply_entry_filters(
            entries,
            search=params.get_text(request, "search"),
            organization=params.get_text(request, "organization"),
            rank_min=params.get_int(request, "rank_min"),
            rank_max=params.get_int(request, "rank_max"),
            metric_min=params.get_float(request, "metric_min"),
            metric_max=params.get_float(request, "metric_max"),
            sample_min=params.get_int(request, "sample_min", minimum=0),
            sample_max=params.get_int(request, "sample_max", minimum=0),
        )
        entries = entries.order_by(
            *params.get_ordering(
                request, allowed=OVERVIEW_ORDERING, default=DEFAULT_OVERVIEW_ORDERING
            )
        )

        page = self.paginate(entries)

        wanted = params.get_list(request, "include_categories", INTERSECTED_CATEGORIES)
        # `get_list` returns `None` for "parameter absent", which for a *set* of
        # blocks means all of them, not none. Without this, omitting the
        # parameter silently returned three-quarters-null blocks and reported
        # `categories_included: []` -- contradicting the documented contract that
        # every category block is present on every row and explicitly null only
        # where the model was not evaluated.
        if wanted is None:
            wanted = list(INTERSECTED_CATEGORIES)
        wanted = [category for category in wanted if category in INTERSECTED_CATEGORIES]
        blocks = selectors.category_blocks([entry.model_key for entry in page], wanted)

        rows = [serializers.overview_row(entry, blocks) for entry in page]
        return self.finish(rows, extra_meta={"categories_included": wanted})


# --------------------------------------------------------------------------- #
# 2. /categories/
# --------------------------------------------------------------------------- #


class CategoryIndexView(LeaderboardView):
    """A fixed-size index, so it is not paginated -- but it still carries `meta`
    so the frontend's freshness badge behaves identically on every call."""

    def get(self, request) -> Response:
        return Response(
            {
                "results": [selectors.category_summary(category) for category in CATEGORIES],
                "meta": self.meta(
                    {"primary_category": PRIMARY_CATEGORY, "matched_agent_models": _matched_key_count()}
                ),
            }
        )


# --------------------------------------------------------------------------- #
# 3. /categories/{category}/
# --------------------------------------------------------------------------- #


class CategoryView(LeaderboardView):
    """One LMArena category, unfiltered by completeness.

    `in_agent_set` defaults to **true** -- the spec's retained subset -- but
    `?in_agent_set=false` returns the rows that were excluded, and
    `?scope=all` drops the filter entirely. Those rows are the reason the
    intersection is auditable rather than merely asserted.
    """

    def get(self, request, category: str) -> Response:
        if category not in CATEGORIES:
            raise UnknownValue("category", category, allowed=CATEGORIES)

        entries = selectors.active_entries(category)

        scope_all = (params.get_text(request, "scope") or "").lower() == "all"
        if scope_all:
            in_agent_set = None
        else:
            in_agent_set = params.get_bool(request, "in_agent_set", default=True)
        if in_agent_set is not None:
            entries = entries.filter(in_agent_set=in_agent_set)

        entries = self._apply_match_filter(entries, params.get_bool(request, "matched"))

        entries = selectors.apply_entry_filters(
            entries,
            search=params.get_text(request, "search"),
            organization=params.get_text(request, "organization"),
            rank_min=params.get_int(request, "rank_min"),
            rank_max=params.get_int(request, "rank_max"),
            metric_min=params.get_float(request, "min_metric"),
            metric_max=params.get_float(request, "max_metric"),
            sample_min=params.get_int(request, "min_sample_size", minimum=0),
            sample_max=params.get_int(request, "max_sample_size", minimum=0),
        )
        entries = entries.order_by(
            *params.get_ordering(
                request, allowed=CATEGORY_ORDERING, default=DEFAULT_CATEGORY_ORDERING
            )
        )

        page = self.paginate(entries)
        rows = [serializers.category_row(entry) for entry in page]
        return self.finish(
            rows,
            extra_meta={
                "category": category,
                "metric_kind": selectors.category_summary(category)["metric_kind"],
                "in_agent_set": in_agent_set,
                "scope": "all" if scope_all else None,
            },
        )

    @staticmethod
    def _apply_match_filter(queryset, matched: bool | None):
        """`matched` means "has an AA match", reached through the agent key."""
        if matched is None:
            return queryset
        keys = _matched_keys()
        return queryset.filter(agent_key__in=keys) if matched else queryset.exclude(
            agent_key__in=keys
        )


def _matched_keys() -> list[str]:
    return list(ModelMatch.objects.values_list("lmarena_entry__model_key", flat=True))


def _matched_key_count() -> int:
    return ModelMatch.objects.count()


# --------------------------------------------------------------------------- #
# 4. /artificial-analysis/
# --------------------------------------------------------------------------- #


class ArtificialAnalysisView(LeaderboardView):
    """The AA catalogue, single-source.

    `retained` defaults to true: the model set this project's scope covers, i.e.
    records that are also present in LMArena's `agent` split. It is a plain
    boolean, and `retained=false` selects the **complement** -- the AA records
    with no agent-set presence -- not the union. Two recipes follow from that,
    and both are used during a match review:

    * AA models with no LMArena counterpart:
      ``?retained=false&matched=false``. An unmatched record is never retained,
      so the two filters together name exactly that population, and this is how
      a reviewer decides whether a gap is our normalizer's fault or AA's
      coverage.
    * the whole AA catalogue: both calls. There is deliberately no parameter that
      lifts the retention filter entirely, because "everything AA publishes" is a
      review-time question rather than a serving-time one.
    """

    def get(self, request) -> Response:
        unknown = selectors.unknown_aa_filters(request, AA_NUMERIC_FIELDS)
        if unknown:
            raise InvalidParameter(
                unknown[0],
                f"Unknown metric filter {unknown[0]!r}.",
                allowed=sorted(f"min_{key}" for key in AA_NUMERIC_FIELDS)
                + sorted(f"max_{key}" for key in AA_NUMERIC_FIELDS),
            )

        models = LLMModel.objects.filter(is_active=True).select_related(
            "creator", "lmarena_match__lmarena_entry"
        )

        retained = params.get_bool(request, "retained", default=True)
        if retained is not None:
            models = models.filter(is_retained=retained)

        matched = params.get_bool(request, "matched")
        if matched is not None:
            models = models.filter(lmarena_match__isnull=not matched)

        search = params.get_text(request, "search")
        if search:
            models = models.filter(Q(name__icontains=search) | Q(slug__icontains=search))

        creator = params.get_text(request, "creator")
        if creator:
            models = models.filter(creator__name__icontains=creator)

        version = params.get_float(request, "intelligence_index_version")
        if version is not None:
            models = models.filter(intelligence_index_version=version)

        released_after = params.get_text(request, "release_date_after")
        if released_after:
            models = models.filter(release_date__gte=_as_date(released_after, "release_date_after"))

        released_before = params.get_text(request, "release_date_before")
        if released_before:
            models = models.filter(
                release_date__lte=_as_date(released_before, "release_date_before")
            )

        models = selectors.apply_aa_numeric_filters(
            models, request=request, allowed=AA_NUMERIC_FIELDS
        )
        models = models.order_by(
            *params.get_ordering(request, allowed=AA_ORDERING, default=DEFAULT_AA_ORDERING)
        )

        page = self.paginate(models)
        rows = [serializers.aa_row(model) for model in page]
        return self.finish(
            rows,
            extra_meta={
                "retained": retained,
                "metric_fields": sorted(AA_NUMERIC_FIELDS),
            },
        )


def _as_date(value: str, param: str) -> date:
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        raise InvalidParameter(param, f"{param} must be an ISO date (YYYY-MM-DD).") from None


# --------------------------------------------------------------------------- #
# 5. /models/{key}/
# --------------------------------------------------------------------------- #


class ModelDetailView(LeaderboardView):
    """One model, every block.

    **Complete entries only.** A model that is real but has no counterpart in
    the other source returns 404 `model_incomplete` with its unmatched reason,
    rather than a half-populated row the frontend would have to defend against.

    Note the distinction the 404 preserves: a category the model was simply
    never evaluated in is a `null` block inside a 200, while a missing
    *cross-source join* is the 404. The first is information; the second is the
    case this project chooses not to serve.
    """

    def get(self, request, key: str) -> Response:
        entry, model = selectors.resolve_model(key)

        if entry is None and model is None:
            elsewhere = selectors.entry_in_any_category(key)
            if elsewhere is not None:
                raise ModelIncomplete(
                    key,
                    "not_in_agent_set",
                    message=(
                        f"{elsewhere.model_name!r} appears in LMArena's "
                        f"{elsewhere.category!r} category but not in the `agent` split, "
                        "so it has no joined representation. It remains available "
                        f"through /categories/{elsewhere.category}/."
                    ),
                    detail={"category": elsewhere.category, "model_name": elsewhere.model_name},
                )
            return self._not_found(key)

        if entry is None:
            raise ModelIncomplete(
                key,
                "not_in_agent_set",
                message=(
                    f"{model.name!r} exists in Artificial Analysis but has no LMArena "
                    "`agent` entry, so it has no joined representation. It remains "
                    "available through /artificial-analysis/."
                ),
                detail={"aa_slug": model.slug, "aa_id": model.aa_id},
            )

        if model is None:
            raise ModelIncomplete(
                key,
                UnmatchedReason.NO_AA_MATCH.value,
                message=(
                    f"{entry.model_name!r} is in LMArena's `agent` split, but no "
                    "Artificial Analysis record resolved to it at the same reasoning "
                    "level. It is therefore not served by the joined endpoints. It "
                    "remains available through /categories/agent/ and /unmatched/; "
                    "a `ModelAlias` is the way to join it."
                ),
                detail={
                    "model_name": entry.model_name,
                    "rank": entry.rank,
                    "agent_key": entry.agent_key,
                    # Fully scoped, and each part is load-bearing. The ledger row
                    # for this 404 is the one the AA refresh writes against the
                    # *agent* side (`no_aa_match`), not an AA-sourced row: the
                    # direction matters, since "no AA record resolved here" and
                    # "this AA record resolved nowhere" are different findings.
                    # Category and reason then exclude a same-keyed row that
                    # answers something else entirely -- a webdev duplicate, or an
                    # agent dedupe loser. An unscoped lookup returns whichever of
                    # those sorts first and presents it as the reason.
                    "unmatched": _serializable(
                        selectors.unmatched_reason_for(
                            entry.model_key,
                            source=Source.LMARENA.value,
                            category=PRIMARY_CATEGORY,
                            reason=UnmatchedReason.NO_AA_MATCH.value,
                        )
                    ),
                },
            )

        blocks = selectors.category_blocks([entry.model_key], INTERSECTED_CATEGORIES)
        return Response(serializers.model_detail(entry, model, blocks))

    @staticmethod
    def _not_found(key: str) -> Response:
        return Response(
            {
                "error": "not_found",
                "detail": f"No model matches {key!r}.",
                "model_key": key,
            },
            status=404,
        )


def _serializable(value: Any) -> Any:
    """Make a selector's lookup JSON-safe (it may carry datetimes)."""
    if isinstance(value, Mapping):
        return {key: _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if hasattr(value, "isoformat"):
        return serializers.iso(value)
    return value


# --------------------------------------------------------------------------- #
# 6. /metadata/
# --------------------------------------------------------------------------- #


class MetadataView(LeaderboardView):
    """The freshness and status contract.

    Three states the frontend must render differently, and all three are
    distinguishable here rather than being collapsed into "no data":

    * never refreshed -- `last_success_at` is null and `is_stale` is true;
    * refresh failing -- `last_status` is not a success while `last_success_at`
      still points at the last good run;
    * simply old -- `is_stale` true with a non-null `last_success_at`.

    `configured: false` (no AA key) is a fourth state, and a benign one.
    """

    def get(self, request) -> Response:
        recent = [
            serializers.sync_run_row(run)
            for run in SyncRun.objects.order_by("-started_at")[:RECENT_RUNS]
        ]
        return Response(
            {
                "sources": {
                    Source.LMARENA.value: selectors.source_freshness(
                        Source.LMARENA.value, stale_after_seconds=stale_after_seconds()
                    ),
                    Source.ARTIFICIAL_ANALYSIS.value: selectors.source_freshness(
                        Source.ARTIFICIAL_ANALYSIS.value,
                        stale_after_seconds=stale_after_seconds(),
                    ),
                },
                "counts": selectors.global_counts(),
                "categories": [selectors.category_summary(c) for c in CATEGORIES],
                "matching": selectors.matching_tallies(),
                "recent_runs": recent,
                "config": {
                    "harness_fold_enabled": bool(
                        getattr(settings, "LEADERBOARD_ENABLE_HARNESS_FOLD", True)
                    ),
                    "stale_after_seconds": stale_after_seconds(),
                },
                "attribution": {
                    "artificial_analysis": "https://artificialanalysis.ai/",
                    "lmarena": "https://lmarena.ai/",
                },
                "meta": self.meta(),
            }
        )


# --------------------------------------------------------------------------- #
# 7. /unmatched/
# --------------------------------------------------------------------------- #


class UnmatchedView(LeaderboardView):
    """The exclusions, made visible to the frontend rather than only to ops.

    This is what keeps the completeness rule honest: every row the joined
    endpoints drop is listed here with a reason, so "not served" never becomes
    "not knowable".
    """

    def get(self, request) -> Response:
        source = params.get_text(request, "source")
        if source is not None and source not in Source.values:
            raise UnknownValue("source", source, allowed=Source.values)

        category = params.get_text(request, "category")
        if category is not None and category not in CATEGORIES:
            raise UnknownValue("category", category, allowed=CATEGORIES)

        records = UnmatchedRecord.objects.all()

        current = params.get_bool(request, "current", default=True)
        if current is not None:
            records = records.filter(is_current=current)

        # `reason` is free-form against the model's choices: an unknown one
        # simply matches nothing, which is friendlier than a 404 for a filter.
        reason = params.get_text(request, "reason")
        if reason:
            records = records.filter(reason=reason)

        if source:
            records = records.filter(source=source)
        if category:
            records = records.filter(category=category)

        search = params.get_text(request, "search")
        if search:
            records = records.filter(model_name__icontains=search)

        records = records.order_by(
            *params.get_ordering(
                request, allowed=UNMATCHED_ORDERING, default=DEFAULT_UNMATCHED_ORDERING
            )
        )

        page = self.paginate(records)
        rows = [serializers.unmatched_row(record) for record in page]
        return self.finish(rows)
