"""Query construction -- the whole read side of the API.

Every queryset the views execute is built here, which keeps two rules
enforceable in one place:

1. **The completeness rule is a filter, not a stored flag.** `complete_agent_entries()`
   requires a live AA match, so the joined surface is derived from the match
   table on every request. A stored `is_complete` column would instead be a
   second source of truth that drifts from the match it is supposed to
   summarize. What this does *not* buy is read-time alias resolution: the ladder
   runs during a refresh, so a `ModelAlias` shows up on `/overview/` from the
   next refresh onwards -- never mid-request, and never by inference here.
2. **`is_active` is always applied.** Deactivated rows exist so the previous
   state stays inspectable, but they are never part of a default response.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from django.conf import settings
from django.db.models import Max, Min, Q, QuerySet

from ..constants import (
    CATEGORIES,
    PRIMARY_CATEGORY,
    SUCCESSFUL_STATUSES,
    Source,
    SyncStatus,
)
from ..models import LMArenaEntry, LLMModel, SyncRun, UnmatchedRecord

# --------------------------------------------------------------------------- #
# Base querysets
# --------------------------------------------------------------------------- #


def active_entries(category: str) -> QuerySet[LMArenaEntry]:
    return LMArenaEntry.objects.filter(category=category, is_active=True)


def agent_entries() -> QuerySet[LMArenaEntry]:
    return active_entries(PRIMARY_CATEGORY)


def complete_agent_entries() -> QuerySet[LMArenaEntry]:
    """The completeness rule, expressed as one queryset.

    Complete means: an `agent` row **and** a live matched AA record. That is the
    whole rule -- it deliberately does *not* require the model to appear in
    `document`/`search`/`webdev`. A model that was simply never evaluated in a
    category still renders, with that category present as an explicit `null`;
    absence of a category is real information, while absence of the cross-source
    join is not.
    """
    return agent_entries().filter(
        aa_match__isnull=False,
        aa_match__model__is_active=True,
    ).select_related("aa_match__model__creator")


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


def apply_entry_filters(
    queryset: QuerySet[LMArenaEntry],
    *,
    search: str | None = None,
    organization: str | None = None,
    rank_min: int | None = None,
    rank_max: int | None = None,
    metric_min: float | None = None,
    metric_max: float | None = None,
    sample_min: int | None = None,
    sample_max: int | None = None,
) -> QuerySet[LMArenaEntry]:
    if search:
        queryset = queryset.filter(
            Q(model_name__icontains=search) | Q(organization__icontains=search)
        )
    if organization:
        queryset = queryset.filter(organization__iexact=organization)
    if rank_min is not None:
        queryset = queryset.filter(rank__gte=rank_min)
    if rank_max is not None:
        queryset = queryset.filter(rank__lte=rank_max)
    if metric_min is not None:
        queryset = queryset.filter(metric_value__gte=metric_min)
    if metric_max is not None:
        queryset = queryset.filter(metric_value__lte=metric_max)
    if sample_min is not None:
        queryset = queryset.filter(sample_size__gte=sample_min)
    if sample_max is not None:
        queryset = queryset.filter(sample_size__lte=sample_max)
    return queryset


def apply_aa_numeric_filters(
    queryset: QuerySet[LLMModel],
    *,
    request,
    allowed: Mapping[str, str],
) -> QuerySet[LLMModel]:
    """Apply `min_<field>` / `max_<field>` for every whitelisted metric.

    Only the whitelisted names are read out of `request`, so an unknown metric
    in the query string is simply never looked at -- it cannot reach the ORM.
    `params` is responsible for rejecting anything malformed that *is* known.
    """
    from . import params as param_helpers

    for key, field in allowed.items():
        low = param_helpers.get_float(request, f"min_{key}")
        if low is not None:
            queryset = queryset.filter(**{f"{field}__gte": low})
        high = param_helpers.get_float(request, f"max_{key}")
        if high is not None:
            queryset = queryset.filter(**{f"{field}__lte": high})
    return queryset


def unknown_aa_filters(request, allowed: Mapping[str, str]) -> list[str]:
    """`min_x`/`max_x` parameters that name a metric outside the whitelist."""
    known = set(allowed)
    unknown = []
    for raw in request.query_params:
        for prefix in ("min_", "max_"):
            if raw.startswith(prefix) and raw[len(prefix) :] not in known:
                unknown.append(raw)
    return sorted(set(unknown))


# --------------------------------------------------------------------------- #
# Category blocks
# --------------------------------------------------------------------------- #


def _better(candidate: LMArenaEntry, current: LMArenaEntry | None) -> LMArenaEntry:
    """Choose between two rows that share an `agent_key` within one category.

    This happens when a category contains both the exact model and a
    harness-wrapped variant of it (`gpt-5.6-sol-xhigh` and
    `gpt-5.6-sol-xhigh (codex-harness)` both belong to the same agent model).
    The exact row always wins; otherwise the better rank does. Deterministic, so
    two identical requests cannot return different rows.
    """
    if current is None:
        return candidate
    candidate_exact = candidate.model_key == candidate.agent_key
    current_exact = current.model_key == current.agent_key
    if candidate_exact != current_exact:
        return candidate if candidate_exact else current
    candidate_rank = candidate.rank if candidate.rank is not None else 10**9
    current_rank = current.rank if current.rank is not None else 10**9
    if candidate_rank != current_rank:
        return candidate if candidate_rank < current_rank else current
    return candidate if candidate.model_key < current.model_key else current


def category_blocks(
    agent_keys: Sequence[str],
    categories: Iterable[str],
) -> dict[str, dict[str, LMArenaEntry]]:
    """`{category: {agent_key: entry}}` for a page of agent models.

    One query per category rather than one per row -- a page of 50 models with
    three category blocks would otherwise be 151 queries.
    """
    keys = [key for key in agent_keys if key]
    if not keys:
        return {category: {} for category in categories}

    blocks: dict[str, dict[str, LMArenaEntry]] = {}
    for category in categories:
        rows = LMArenaEntry.objects.filter(
            category=category,
            is_active=True,
            agent_key__in=keys,
        )
        grouped: dict[str, LMArenaEntry] = {}
        for row in rows:
            grouped[row.agent_key] = _better(row, grouped.get(row.agent_key))
        blocks[category] = grouped
    return blocks


def full_category_blocks(agent_key: str) -> dict[str, LMArenaEntry]:
    """All four blocks for one model, including `agent` itself."""
    blocks: dict[str, LMArenaEntry] = {}
    for category, grouped in category_blocks([agent_key], CATEGORIES).items():
        entry = grouped.get(agent_key)
        if entry is not None:
            blocks[category] = entry
    return blocks


# --------------------------------------------------------------------------- #
# Model resolution
# --------------------------------------------------------------------------- #


def resolve_model(key: str) -> tuple[LMArenaEntry | None, LLMModel | None]:
    """Resolve a path key to ``(agent_entry, aa_model)``.

    ================================  =========================================
    result                            meaning
    ================================  =========================================
    ``(entry, model)``                complete -- serve it
    ``(entry, None)``                 agent row exists, no AA match
    ``(None, model)``                 AA record exists, no agent row
    ``(None, None)``                  nothing by this key
    ================================  =========================================

    Resolution order is `agent model_key` -> AA `slug` -> AA `id`, i.e. the same
    identity the frontend was handed by `/overview/` first, then the two AA
    spellings. The AA slug rung is verbatim *and* normalized, because the AA
    slug and the agent key are different namespaces that frequently look alike
    (`gpt-5-5` is both) -- the agent row wins, which is the intent, since the
    joined endpoints are agent-anchored.
    """
    from ..normalization import normalize_model_key

    normalized = normalize_model_key(key)

    entry = (
        agent_entries()
        .filter(Q(model_key=normalized) | Q(agent_key=normalized))
        .select_related("aa_match__model__creator")
        .order_by("rank", "pk")
        .first()
    )
    if entry is not None:
        match = getattr(entry, "aa_match", None)
        return entry, (match.model if match is not None else None)

    model = (
        LLMModel.objects.filter(is_active=True)
        .filter(Q(slug=key) | Q(aa_id=key) | Q(slug=normalized))
        .select_related("creator")
        .first()
    )
    return None, model


def entry_in_any_category(key: str) -> LMArenaEntry | None:
    """Find the key in a non-agent category, for a better 404 message."""
    from ..normalization import normalize_model_key

    normalized = normalize_model_key(key)
    return (
        LMArenaEntry.objects.filter(is_active=True)
        .filter(Q(model_key=normalized) | Q(agent_key=normalized))
        .exclude(category=PRIMARY_CATEGORY)
        .order_by("category", "rank", "pk")
        .first()
    )


def unmatched_reason_for(
    key: str,
    *,
    source: str | None = None,
    category: str | None = None,
    reason: str | None = None,
) -> dict[str, Any] | None:
    """The recorded ledger entry explaining why this model is not joined.

    `source`, `category` and `reason` are not filters of convenience --
    omitting them lets the lookup return a row that answers a *different
    question*. A ledger row is keyed by the key of the side that failed to
    match, so searching for an `agent` key with no source restriction can
    surface, say, a `webdev` duplicate-collapse record that happens to share the
    key and present it as the reason the model is missing from `/overview/`.
    Callers that know which join they are asking about must say so.

    `reason` earns its place the same way: one agent key can carry several
    current rows (a dedupe loser that also has no AA match), and the newest one
    is not necessarily the one being asked about. A caller rendering the
    `no_aa_match` 404 means "why is there no AA match", and must say so rather
    than take whichever row sort happened to put first.
    """
    from ..normalization import normalize_model_key

    records = UnmatchedRecord.objects.filter(model_key=normalize_model_key(key))
    if source is not None:
        records = records.filter(source=source)
    if category is not None:
        records = records.filter(category=category)
    if reason is not None:
        records = records.filter(reason=reason)

    record = records.order_by("-is_current", "-last_seen_at").first()
    if record is None:
        return None
    return {
        "source": record.source,
        "category": record.category or None,
        "reason": record.reason,
        "detail": record.detail or {},
        "last_seen_at": record.last_seen_at,
    }


# --------------------------------------------------------------------------- #
# Freshness and status
# --------------------------------------------------------------------------- #


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def now() -> datetime:
    return datetime.now(tz=timezone.utc)


def source_freshness(source: str, *, stale_after_seconds: int) -> dict[str, Any]:
    """Everything the frontend needs to say "data as of ...".

    Derived from `SyncRun` on every request. Deliberately not denormalized onto
    the data tables: staleness depends on "now", so any stored flag is wrong the
    moment it is written.

    **Dry runs are excluded throughout**, not merely from the success lookup.
    They write nothing -- the whole transaction is rolled back -- so treating one
    as the latest attempt would produce a self-contradicting block: "last
    attempt: today, status: success, last success: yesterday". Worse, a
    `--dry-run` before a change would make a stale board report `is_stale: false`
    and switch off the one alarm that says the data has stopped arriving. A
    rehearsal is a rehearsal, not a refresh; `/metadata/`'s `recent_runs` lists
    them with `dry_run: true` so they stay visible to operators.
    """
    refreshes = SyncRun.objects.filter(source=source, dry_run=False)
    last_attempt = refreshes.order_by("-started_at").first()
    last_success = (
        refreshes.filter(status__in=SUCCESSFUL_STATUSES).order_by("-finished_at").first()
    )

    succeeded_at = _aware(last_success.finished_at) if last_success else None
    reference = now()
    age_seconds = int((reference - succeeded_at).total_seconds()) if succeeded_at else None

    if source == Source.ARTIFICIAL_ANALYSIS.value:
        configured = bool(getattr(settings, "AA_API_KEY", ""))
    else:
        configured = True

    # Three distinct states, and the frontend must render them differently:
    # never-refreshed (no success yet), refresh-failing (`last_status` not a
    # success), and simply old (`is_stale`).
    is_stale = age_seconds is None or age_seconds > stale_after_seconds

    info: dict[str, Any] = {
        "configured": configured,
        "last_attempt_at": _aware(last_attempt.started_at) if last_attempt else None,
        "last_status": last_attempt.status if last_attempt else None,
        "last_success_at": succeeded_at,
        "age_seconds": age_seconds,
        "is_stale": is_stale,
        "stale_after_seconds": stale_after_seconds,
        "last_error": (
            {"code": last_attempt.error_code, "message": last_attempt.error_message}
            if last_attempt and last_attempt.error_code
            else None
        ),
    }

    if source == Source.ARTIFICIAL_ANALYSIS.value and last_attempt is not None:
        info["tier"] = last_attempt.tier or None
        info["rate_limit"] = {
            "limit": last_attempt.rate_limit_limit,
            "remaining": last_attempt.rate_limit_remaining,
            "reset_at": _aware(last_attempt.rate_limit_reset_at),
        }
        info["pages_fetched"] = last_attempt.pages_fetched
        info["intelligence_index_version"] = last_attempt.intelligence_index_version

    if source == Source.LMARENA.value and last_attempt is not None:
        info["fields_succeeded"] = list(last_attempt.fields_succeeded or [])
        info["fields_failed"] = dict(last_attempt.fields_failed or {})
        info["dataset_revision"] = last_attempt.dataset_revision or None

    return info


def freshness_summary(*, stale_after_seconds: int) -> dict[str, Any]:
    """The `meta` block attached to every paginated response."""
    return {
        "generated_at": now(),
        "sources": {
            Source.LMARENA.value: source_freshness(
                Source.LMARENA.value, stale_after_seconds=stale_after_seconds
            ),
            Source.ARTIFICIAL_ANALYSIS.value: source_freshness(
                Source.ARTIFICIAL_ANALYSIS.value, stale_after_seconds=stale_after_seconds
            ),
        },
    }


def global_counts() -> dict[str, Any]:
    from ..models import ModelMatch

    return {
        "lmarena_entries": LMArenaEntry.objects.filter(is_active=True).count(),
        "lmarena_agent_entries": agent_entries().count(),
        "complete_agent_entries": complete_agent_entries().count(),
        "aa_models": LLMModel.objects.filter(is_active=True).count(),
        "aa_models_retained": LLMModel.objects.filter(is_active=True, is_retained=True).count(),
        "matches": ModelMatch.objects.count(),
        "unmatched_records": UnmatchedRecord.objects.filter(is_current=True).count(),
    }


def category_summary(category: str) -> dict[str, Any]:
    """Per-category counts for `/categories/` -- so the frontend can build its
    tabs from real data and see an empty intersection *before* requesting it."""
    queryset = active_entries(category)
    ranks = queryset.aggregate(min_rank=Min("rank"), max_rank=Max("rank"))
    latest_publish = (
        queryset.exclude(leaderboard_publish_date=None)
        .order_by("-leaderboard_publish_date")
        .values_list("leaderboard_publish_date", flat=True)
        .first()
    )
    return {
        "category": category,
        "metric_kind": queryset.values_list("metric_kind", flat=True).first(),
        "entry_count": queryset.count(),
        "in_agent_set_count": queryset.filter(in_agent_set=True).count(),
        "rank_min": ranks["min_rank"],
        "rank_max": ranks["max_rank"],
        "latest_publish_date": latest_publish,
    }


def matching_tallies() -> dict[str, int]:
    from ..models import ModelMatch

    tallies: dict[str, int] = defaultdict(int)
    for method in ModelMatch.objects.values_list("match_method", flat=True):
        tallies[method] += 1
    return dict(sorted(tallies.items()))


__all__ = [
    "SyncStatus",
    "active_entries",
    "agent_entries",
    "apply_aa_numeric_filters",
    "apply_entry_filters",
    "category_blocks",
    "category_summary",
    "complete_agent_entries",
    "entry_in_any_category",
    "freshness_summary",
    "full_category_blocks",
    "global_counts",
    "matching_tallies",
    "now",
    "resolve_model",
    "source_freshness",
    "unknown_aa_filters",
    "unmatched_reason_for",
]
