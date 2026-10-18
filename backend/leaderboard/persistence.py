"""Every database write in the leaderboard app lives here.

The "don't destroy the last good data" rules are enforced at this layer:

1. **Source tables are never `DELETE`d.** A vanished model is deactivated
   (`is_active=False`), so the previous state remains inspectable. The single
   exception is `ModelMatch`, which is *derived* data rather than source data:
   it is rebuilt inside the same transaction that writes the run's data, so a
   failure rolls the rebuild back along with everything else and the previous
   matches survive untouched.
2. **`deactivate_missing` runs only on a fully successful fetch with records
   seen.** A partial or empty response must never be able to blank the board --
   that is the specific failure mode this guards.
3. **Timestamps are passed in, never taken from `auto_now`.** A refresh writes
   one consistent `synced_at` across every row it touches, which is what makes
   idempotency testable.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from django.db.models import Q

from .constants import SUCCESSFUL_STATUSES, SyncStatus
from .hn_parsing import ParsedComment, ParsedStoryHit, ParsedTree
from .matching import Claim
from .models import (
    DiscussionTag,
    HNComment,
    HNThread,
    LLMModel,
    LMArenaEntry,
    ModelCreator,
    ModelMatch,
    ProviderEntity,
    SyncRun,
    UnmatchedRecord,
)
from .validation import ParsedAAModel, ParsedLMArenaRow

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# --------------------------------------------------------------------------- #
# Run bookkeeping
# --------------------------------------------------------------------------- #


@dataclass
class UpsertStats:
    """Per-run counters, persisted onto the `SyncRun` row."""

    seen: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    failed: int = 0
    deduplicated: int = 0
    anomalies: int = 0


def reap_stale_running(source: str, *, older_than_seconds: int = 6 * 3600) -> int:
    """Fail `running` rows a killed worker left behind.

    Without this, one SIGKILLed worker strands a `running` row and the partial
    unique index then blocks every future refresh for that source, permanently.
    """
    cutoff = utcnow() - timedelta(seconds=older_than_seconds)
    return (
        SyncRun.objects.filter(
            source=source,
            status=SyncStatus.RUNNING.value,
            started_at__lt=cutoff,
        )
        .update(
            status=SyncStatus.FAILED.value,
            finished_at=utcnow(),
            error_code="reaped",
            error_message="Marked failed by reap_stale_running; the worker never finished.",
        )
    )


def open_run(
    source: str,
    *,
    triggered_by: str = "",
    dry_run: bool = False,
    celery_task_id: str = "",
) -> SyncRun:
    """Create the `running` row, committed immediately.

    Deliberately outside the data transaction: a run that fails must still leave
    a record explaining why.
    """
    return SyncRun.objects.create(
        source=source,
        status=SyncStatus.RUNNING.value,
        triggered_by=triggered_by,
        dry_run=dry_run,
        celery_task_id=celery_task_id,
        started_at=utcnow(),
    )


def finish_run(run: SyncRun, status: str, **fields: Any) -> SyncRun:
    """Write the terminal state of a run."""
    finished = utcnow()
    run.status = status
    run.finished_at = finished
    run.duration_ms = int((finished - run.started_at).total_seconds() * 1000)
    for key, value in fields.items():
        setattr(run, key, value)
    run.save()
    return run


def fail_run(run: SyncRun, error: Exception) -> SyncRun:
    """Record a failure without touching any data written by earlier runs."""
    code = getattr(error, "code", "unexpected_error")
    detail = getattr(error, "detail", None)
    message = f"{type(error).__name__}: {error}"
    if detail:
        message = f"{message} | {detail}"
    return finish_run(
        run,
        SyncStatus.FAILED.value,
        error_code=str(code),
        error_message=message,
    )


def last_success_at(source: str) -> datetime | None:
    """When this source last produced good data. Derived, never denormalized.

    Dry runs are excluded, and must be: a `--dry-run` writes no data -- it rolls
    its whole transaction back -- so counting one here would let a rehearsal
    declare the board fresh. An operator checking the match rate before a change
    would thereby silence the staleness alarm on data that is a day old.
    Rehearsals remain visible in `/metadata/`'s `recent_runs`, where they carry
    `dry_run: true` and are distinguishable from the real thing.
    """
    return (
        SyncRun.objects.filter(
            source=source, status__in=SUCCESSFUL_STATUSES, dry_run=False
        )
        .order_by("-finished_at")
        .values_list("finished_at", flat=True)
        .first()
    )


# --------------------------------------------------------------------------- #
# Upsert helpers
# --------------------------------------------------------------------------- #


def _apply(obj: Any, values: Mapping[str, Any]) -> bool:
    """Assign `values` onto `obj`, reporting whether anything actually moved."""
    changed = False
    for name, value in values.items():
        if getattr(obj, name) != value:
            setattr(obj, name, value)
            changed = True
    return changed


def _upsert(model: Any, identity: Mapping[str, Any], values: Mapping[str, Any], *, synced_at: datetime):
    """One row, keyed by `identity`. Returns ``(obj, "created"|"updated"|"unchanged")``."""
    obj = model.objects.filter(**identity).first()
    if obj is None:
        obj = model(**identity, **values, first_seen_at=synced_at, last_synced_at=synced_at)
        obj.save()
        return obj, "created"

    changed = _apply(obj, values)
    obj.last_synced_at = synced_at
    # `first_seen_at` is deliberately absent from the update: it records when we
    # first saw the record, not when we last refreshed it.
    obj.save(update_fields=[*values.keys(), "last_synced_at"])
    return obj, ("updated" if changed else "unchanged")


# --------------------------------------------------------------------------- #
# Artificial Analysis
# --------------------------------------------------------------------------- #


def upsert_creators(creators: Mapping[str, str], *, synced_at: datetime) -> dict[str, ModelCreator]:
    """Upsert AA `model_creator` records, keyed by their UUID."""
    resolved: dict[str, ModelCreator] = {}
    for aa_id, name in creators.items():
        obj, _ = _upsert(ModelCreator, {"aa_id": aa_id}, {"name": name}, synced_at=synced_at)
        resolved[aa_id] = obj
    return resolved


def upsert_aa_models(
    parsed: Sequence[ParsedAAModel],
    *,
    creators: Mapping[str, ModelCreator],
    retained_aa_ids: set[str],
    synced_at: datetime,
    stats: UpsertStats,
) -> dict[str, LLMModel]:
    """Write the AA catalogue. Returns `aa_id` -> `LLMModel` for the matched set."""
    by_aa_id: dict[str, LLMModel] = {}

    for record in parsed:
        creator = creators.get(record.creator_aa_id or "")
        values = {
            "slug": record.slug,
            "name": record.name,
            "creator": creator,
            "release_date": record.release_date,
            "intelligence_index_version": record.intelligence_index_version,
            "intelligence_index": record.intelligence_index,
            "coding_index": record.coding_index,
            "agentic_index": record.agentic_index,
            "intelligence_index_total_cost": record.intelligence_index_total_cost,
            "cost_per_task": record.cost_per_task,
            "price_1m_input_tokens": record.price_1m_input_tokens,
            "price_1m_output_tokens": record.price_1m_output_tokens,
            "price_1m_cache_hit_tokens": record.price_1m_cache_hit_tokens,
            "price_1m_cache_write_tokens": record.price_1m_cache_write_tokens,
            "median_output_tokens_per_second": record.median_output_tokens_per_second,
            "median_time_to_first_token_seconds": record.median_time_to_first_token_seconds,
            "median_time_to_first_answer_token_seconds": (
                record.median_time_to_first_answer_token_seconds
            ),
            "median_end_to_end_response_time_seconds": (
                record.median_end_to_end_response_time_seconds
            ),
            "is_retained": record.aa_id in retained_aa_ids,
            # A model that reappears after being deactivated is active again.
            "is_active": True,
            "raw_payload": record.raw_payload,
        }
        # Keyed on `aa_id`, not `slug`: a slug rename must update this row, not
        # create a second one alongside it.
        obj, outcome = _upsert(LLMModel, {"aa_id": record.aa_id}, values, synced_at=synced_at)
        by_aa_id[record.aa_id] = obj
        stats.seen += 1
        setattr(stats, outcome, getattr(stats, outcome) + 1)

    # Models that are retained but were not claimed by a match stay in the table
    # flagged `is_retained=False`; only the matched ones can be served.
    return by_aa_id


#: Marks a slug vacated so that a different `aa_id` can take it over.
_RELEASED_MARKER = "-released-"
#: Digest widths to try, narrowest first. 64 hex chars is a full SHA-256, so the
#: last step cannot collide with anything but itself.
_RELEASED_DIGEST_LENGTHS: tuple[int, ...] = (16, 24, 32, 64)


@dataclass(frozen=True)
class ReleasedSlug:
    """One row whose public slug was handed to a different `aa_id`."""

    model: LLMModel
    old_slug: str
    new_owner_aa_id: str
    #: True only when the row is absent from the payload -- then the released
    #: slug is its committed state and the caller has to report it. When the row
    #: is in the payload, `upsert_aa_models` overwrites this value in the same
    #: transaction, so it is never committed and there is nothing to report.
    keeps_released_slug: bool


def _released_slug(slug: str, aa_id: str, *, taken: set[str]) -> str:
    """Derive the value `slug` is vacated to, keeping it unique and in range.

    A readable `f"{slug}-released-{aa_id}"` fails on both counts: the old slug
    alone may be 255 characters, and `aa_id` adds 36 more. Keeping the old slug
    as a prefix and appending a digest of `(aa_id, slug)` bounds the result to
    the column width while staying deterministic, so re-running over the same
    state derives the same value and nothing churns between refreshes.

    `taken` is every slug that must survive the pass -- the payload's own claims
    plus the rows that are not being vacated -- and grows as the caller releases
    slots, which is what rules out a digest collision or a slug that merely
    looks released.
    """
    limit = LLMModel._meta.get_field("slug").max_length
    digest = hashlib.sha256(f"{aa_id}\x00{slug}".encode()).hexdigest()
    for length in _RELEASED_DIGEST_LENGTHS:
        tail = f"{_RELEASED_MARKER}{digest[:length]}"
        candidate = f"{slug[: limit - len(tail)]}{tail}"
        if candidate not in taken:
            return candidate
    raise RuntimeError(f"no free released slug for aa_id={aa_id!r}")  # pragma: no cover


def release_claimed_slugs(parsed: Sequence[ParsedAAModel]) -> list[ReleasedSlug]:
    """Vacate every slug the payload claims for a *different* `aa_id`.

    AA rotates slugs between `aa_id`s across snapshots. The live catalogue has
    zero duplicate slugs, so `slug` being UNIQUE is sound for any one snapshot
    -- but the column is written verbatim while the upsert is keyed on `aa_id`,
    so the *transition* is where two rows disagree about who owns a slug. The
    observed hand-off: bare `jt-4-1-flash-236b-a21b` moved to a newly created
    `aa_id`, with the previous holder renamed to `-non-reasoning`. Rows are
    written one at a time in payload order, so whichever of the two is written
    first raises `IntegrityError` -- on the INSERT branch if the new owner is
    first, on the UPDATE branch if the old one is.

    Freeing the slug up front removes the ordering dependence entirely: after
    this pass no row other than the payload's own owner holds a claimed slug, so
    every later INSERT and UPDATE is free whatever the payload order.

    Must run inside the caller's transaction, immediately before
    `upsert_aa_models`, which is what makes the released value invisible: for a
    row that is in the payload it is overwritten moments later, and for one that
    is not, the row is deactivated by `deactivate_missing_aa_models` and the
    slug is unreachable through the API (`resolve_model` filters `is_active`).
    """
    claimed = {record.slug: record.aa_id for record in parsed}
    if not claimed:
        return []
    incoming_aa_ids = {record.aa_id for record in parsed}

    # Materialized because the rows are modified below, and the table is only a
    # few hundred rows -- cheaper than reasoning about `__in` parameter limits.
    existing = list(LLMModel.objects.only("aa_id", "slug", "name"))
    taken: set[str] = set(claimed)
    taken.update(row.slug for row in existing)

    released: list[ReleasedSlug] = []
    for holder in existing:
        owner = claimed.get(holder.slug)
        # Not claimed at all, or claimed by the row that already holds it (the
        # steady-state case, which must stay a no-op for idempotency).
        if owner is None or owner == holder.aa_id:
            continue
        old_slug = holder.slug
        replacement = _released_slug(old_slug, holder.aa_id, taken=taken)
        taken.add(replacement)
        holder.slug = replacement
        # `last_synced_at` is deliberately untouched: timestamps are passed in,
        # never derived here, and this row is stamped moments later by the
        # upsert or by `deactivate_missing_aa_models`.
        holder.save(update_fields=["slug"])
        released.append(
            ReleasedSlug(
                model=holder,
                old_slug=old_slug,
                new_owner_aa_id=owner,
                keeps_released_slug=holder.aa_id not in incoming_aa_ids,
            )
        )
    return released


def deactivate_missing_aa_models(seen_aa_ids: Iterable[str], *, synced_at: datetime) -> int:
    """Deactivate AA models absent from a *complete* catalogue read.

    The caller is responsible for having established that the read was complete
    -- see `services.refresh`, which only reaches this on a full success.
    """
    return (
        LLMModel.objects.filter(is_active=True)
        .exclude(aa_id__in=list(seen_aa_ids))
        .update(is_active=False, is_retained=False, last_synced_at=synced_at)
    )


# --------------------------------------------------------------------------- #
# LMArena
# --------------------------------------------------------------------------- #


def upsert_lmarena_entries(
    rows: Sequence[ParsedLMArenaRow],
    *,
    agent_key_by_model_key: Mapping[str, str],
    synced_at: datetime,
    stats: UpsertStats,
) -> dict[str, LMArenaEntry]:
    """Write one category's deduplicated rows. Returns `model_key` -> entry.

    `agent_key_by_model_key` maps this category's `model_key` to the `agent`-side
    key it belongs to; a row absent from it is not in the agent set. For the
    `agent` category itself the caller passes an identity mapping, which is why
    every agent row is trivially in the set. Passing the mapping (rather than a
    boolean) is what lets a harness-folded row record *which* agent model it was
    folded into, so the overview can still find it.
    """
    by_key: dict[str, LMArenaEntry] = {}

    for row in rows:
        agent_key = agent_key_by_model_key.get(row.model_key)
        values = {
            "model_name": row.model_name,
            "organization": row.organization,
            "license": row.license,
            "rank": row.rank,
            "metric_kind": row.metric_kind,
            "metric_value": row.metric_value,
            "metric_lower": row.metric_lower,
            "metric_upper": row.metric_upper,
            "metric_variance": row.metric_variance,
            "sample_size": row.sample_size,
            "session_count": row.session_count,
            "leaderboard_publish_date": row.leaderboard_publish_date,
            "in_agent_set": agent_key is not None,
            "agent_key": agent_key,
            "is_active": True,
            "source_metadata": row.source_metadata,
        }
        obj, outcome = _upsert(
            LMArenaEntry,
            {"category": row.category, "model_key": row.model_key},
            values,
            synced_at=synced_at,
        )
        by_key[row.model_key] = obj
        stats.seen += 1
        setattr(stats, outcome, getattr(stats, outcome) + 1)

    return by_key


def deactivate_missing_lmarena_entries(
    category: str, seen_keys: Iterable[str], *, synced_at: datetime
) -> int:
    return (
        LMArenaEntry.objects.filter(category=category, is_active=True)
        .exclude(model_key__in=list(seen_keys))
        .update(is_active=False, last_synced_at=synced_at)
    )


# --------------------------------------------------------------------------- #
# Matches
# --------------------------------------------------------------------------- #


def rebuild_matches(
    claims: Sequence[Claim],
    entries_by_key: Mapping[str, LMArenaEntry],
    models_by_aa_id: Mapping[str, LLMModel],
    *,
    synced_at: datetime,
    stats: UpsertStats,
) -> int:
    """Replace the AA <-> agent join with this run's result.

    `ModelMatch` is derived, not source data: it is fully recomputed from the
    run's own inputs, and the rebuild happens inside the caller's transaction,
    so a failure leaves the previous matches exactly as they were.

    Full replacement rather than incremental upsert because a match can *change*
    -- AA renames a slug and the row now belongs to a different agent key -- and
    the `OneToOneField` on `model` means the old and new owners cannot both hold
    it while the change is applied.
    """
    ModelMatch.objects.all().delete()

    created = 0
    for claim in claims:
        entry = entries_by_key.get(claim.matched_key)
        model = models_by_aa_id.get(claim.model.aa_id)
        if entry is None or model is None:
            stats.failed += 1
            continue
        ModelMatch.objects.create(
            lmarena_entry=entry,
            model=model,
            match_method=claim.method,
            # `<= 4` covers alias, both verbatim rungs and `exact_effort_slug`;
            # only `harness_fold` (rank 5) is an inference. See `Claim.rank`.
            confidence=1.0 if claim.rank <= 4 else 0.75,
            is_manual=claim.method == "alias",
            matched_key=claim.matched_key,
            last_matched_at=synced_at,
        )
        created += 1
    return created


# --------------------------------------------------------------------------- #
# Unmatched reporting
# --------------------------------------------------------------------------- #


class UnmatchedLedger:
    """Accumulates this run's exclusions and closes out the ones that stopped.

    Current-state semantics: upsert per identity, so re-running a refresh does
    not grow the table, and `occurrences` records how persistent a problem is.

    `reasons` scopes `close_stale` to the reasons this ledger is responsible
    for. That is not a convenience: a source's ledger rows are not all written
    by the phase named after that source. "An `agent` model with no AA match" is
    a fact about LMArena, but it is only *knowable* after the AA matching phase
    has run, so `refresh_aa` writes those rows. Two ledgers therefore own rows
    of the same source, and an unscoped `close_stale` in either would flag the
    other's fresh rows stale -- silently emptying the report of exactly the
    population it exists to explain. Scoping makes ownership explicit, and every
    (source, reason) pair belongs to exactly one ledger.
    """

    def __init__(
        self,
        source: str,
        *,
        synced_at: datetime,
        reasons: Sequence[str] | None = None,
    ):
        self.source = source
        self.synced_at = synced_at
        self.reasons = tuple(reasons) if reasons else None
        self._touched_ids: set[int] = set()

    def record(
        self,
        *,
        reason: str,
        model_key: str,
        category: str = "",
        model_name: str = "",
        organization: str = "",
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        if not model_key:
            model_key = model_name or "<unknown>"
        identity = {
            "source": self.source,
            "category": category,
            "reason": reason,
            "model_key": model_key,
        }

        obj = UnmatchedRecord.objects.filter(**identity).first()
        if obj is None:
            obj = UnmatchedRecord.objects.create(
                **identity,
                model_name=model_name,
                organization=organization,
                occurrences=1,
                is_current=True,
                first_seen_at=self.synced_at,
                last_seen_at=self.synced_at,
                detail=dict(detail or {}),
            )
            self._touched_ids.add(obj.id)
            return

        obj.model_name = model_name or obj.model_name
        obj.organization = organization or obj.organization
        obj.occurrences += 1
        obj.is_current = True
        obj.last_seen_at = self.synced_at
        obj.detail = dict(detail or {})
        obj.save(
            update_fields=[
                "model_name",
                "organization",
                "occurrences",
                "is_current",
                "last_seen_at",
                "detail",
            ]
        )
        self._touched_ids.add(obj.id)

    def close_stale(self) -> int:
        """Flag the records this ledger owns that did not recur. Never deletes."""
        stale = UnmatchedRecord.objects.filter(source=self.source, is_current=True)
        if self.reasons is not None:
            stale = stale.filter(reason__in=self.reasons)
        return stale.exclude(id__in=self._touched_ids).update(is_current=False)

    @property
    def count(self) -> int:
        return len(self._touched_ids)


# --------------------------------------------------------------------------- #
# Hacker News discussions
# --------------------------------------------------------------------------- #
#
# This is the one place in the app that DELETEs a source table, and the reason is
# that a discussion is not the same kind of thing as a model measurement.
#
# The no-DELETE rule exists so *the previous state stays inspectable*. For a
# model that vanishes from LMArena or Artificial Analysis, our row is the last
# copy -- upstream has forgotten it, and deleting would destroy the only record.
# A Hacker News thread is the opposite: `GET https://hn.algolia.com/api/v1/items/{id}`
# keeps serving it forever, so an aged-out row is a re-fetchable cache entry and
# its loss is recoverable by one `manage.py refresh_discussions` run.
#
# That is what makes age-based pruning safe, and age-based pruning in turn is
# what lets membership be monotonic: `posted_at` is immutable and the cutoff only
# moves forward, so nothing can re-enter the bank. No `is_active` flag, no
# miss-counter for hysteresis at a rank boundary, no stored `is_top` -- ranking is
# a plain ORDER BY and the table's contents *are* the served set.


def _hn_hit_provenance(raw: Mapping[str, Any]) -> dict[str, Any]:
    """A trimmed copy of a discovery hit, for provenance.

    Algolia attaches `_highlightResult` and `_rankingInfo` blobs that are several
    times the size of the record itself and say nothing about the story, so keys
    prefixed with `_` are dropped. What is left is what a reviewer would want when
    asking "where did this row come from?".
    """
    return {str(key): value for key, value in raw.items() if not str(key).startswith("_")}


def upsert_hn_thread_discovery(
    story: ParsedStoryHit,
    *,
    terms: Sequence[str],
    rank_score: float,
    discovered_by: Sequence[str],
    synced_at: datetime,
    stats: UpsertStats,
) -> tuple[HNThread, str]:
    """Write the discovery metadata for one story. Returns ``(thread, outcome)``.

    Deliberately does **not** touch any tree field. A thread is discovered on one
    run and its tree may be fetched on another (or several), so a discovery
    upsert that wrote `comments_stored`, `fetched_at` or `raw_payload` would blank
    a tree that is perfectly good merely because this hour's refetch budget went
    elsewhere.
    """
    thread = HNThread.objects.filter(hn_id=story.hn_id).first()

    provenance = _hn_hit_provenance(story.raw)
    values: dict[str, Any] = {
        "title": story.title,
        "url": story.url,
        "domain": story.domain,
        "author": story.author,
        "points": story.points,
        "num_comments": story.num_comments,
        "posted_at": story.posted_at,
        "relevance_terms": list(terms),
        "rank_score": rank_score,
    }

    if thread is None:
        thread = HNThread(
            hn_id=story.hn_id,
            first_seen_at=synced_at,
            last_synced_at=synced_at,
            source_metadata={
                "discovered_by": sorted(set(discovered_by)),
                "hit": provenance,
            },
            **values,
        )
        thread.save()
        stats.created += 1
        return thread, "created"

    # Union rather than replace: a thread found by the window query last hour and
    # by the keyword sweep this hour was found by both, and collapsing that to
    # whichever ran last would lose the record of how it was discovered.
    previous = set((thread.source_metadata or {}).get("discovered_by") or ())
    values["source_metadata"] = {
        "discovered_by": sorted(previous | set(discovered_by)),
        "hit": provenance,
    }

    changed = _apply(thread, values)
    thread.last_synced_at = synced_at
    thread.save(update_fields=[*values.keys(), "last_synced_at"])

    outcome = "updated" if changed else "unchanged"
    setattr(stats, outcome, getattr(stats, outcome) + 1)
    return thread, outcome


def record_hn_tree(
    thread: HNThread,
    tree: ParsedTree,
    *,
    synced_at: datetime,
) -> None:
    """Write what a tree fetch produced, on the thread row.

    The counts are stored rather than derived on read, because the read path is
    not allowed to count rows to describe a thread -- the list endpoint would make
    one aggregate query per row.
    """
    thread.comments_stored = len(tree.comments)
    thread.max_depth = tree.max_depth
    thread.tree_truncated = tree.truncated
    thread.fetched_at = synced_at
    thread.raw_payload = tree.skeleton
    thread.save(
        update_fields=[
            "comments_stored",
            "max_depth",
            "tree_truncated",
            "fetched_at",
            "raw_payload",
        ]
    )


@dataclass
class CommentWriteStats:
    """What one thread's comment upsert did.

    Deliberately **not** folded into `UpsertStats`. The `SyncRun` counters
    describe one population, and for this source that population is *threads*:
    mixing comments in would report `created` above `seen`, because discovery only
    ever sees stories. Comment volume belongs in the run's `summary`, where it can
    be read as its own number.
    """

    rows: dict[int, HNComment] = field(default_factory=dict)
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    #: Comments HN moved from another story into this thread. Orthogonal to the
    #: content counters: a reassigned row also counts as `updated`, because its
    #: ownership changed.
    reassigned: int = 0


def upsert_hn_comments(
    thread: HNThread,
    comments: Sequence[ParsedComment],
    *,
    synced_at: datetime,
) -> CommentWriteStats:
    """Bulk-upsert one thread's comments, keyed by HN comment id.

    The returned rows are the point of the return value as much as the counts: the
    tag writer needs *rows*, because a `DiscussionTag` points at a comment by
    foreign key and a tag on a comment created moments ago cannot be built from
    the parsed payload alone.

    Bulk rather than the per-row `_upsert` helper, and that is a concurrency
    decision rather than a stylistic one: `_upsert` issues a SELECT and an UPDATE
    per row, so 600 comments would be ~1,200 statements inside a single `IMMEDIATE`
    transaction, holding SQLite's write lock for seconds while the API's reads
    queue behind it. This loads the thread's rows in one query, diffs in memory,
    and writes in two statements.

    Identity is resolved **globally**, not per thread: `hn_id` is unique across
    the table, and Hacker News reassigns comments between stories when duplicate
    submissions are merged. A row stored under the old thread would therefore be
    invisible to a thread-scoped lookup and the insert would violate the unique
    index. Finding it and moving it to `thread` is the correct reading -- the
    fetched tree is authoritative about where a comment belongs now -- and it
    keeps the row's pk and `first_seen_at`. The old thread's tags are deleted
    because they describe an ownership that no longer holds; the new thread's
    tags are rebuilt by `replace_comment_tags` immediately afterwards.

    Parents are resolved in a second pass because a `bulk_create` is the only
    point at which the new rows have primary keys. `parent_hn_id` is written in the
    first pass and is what the API actually serves; the FK is integrity, not the
    read path. The reassigning update is flushed before that pass re-reads the pk
    map, or a moved parent would be missing and its child's FK silently nulled.
    """
    # `bulk_create` must never receive two objects with one globally-unique
    # `hn_id`. `parse_item_tree` already normalizes the tree; this is the
    # boundary's own guard, so a hand-built sequence cannot crash the run either.
    unique: dict[int, ParsedComment] = {}
    for item in comments:
        unique.setdefault(item.hn_id, item)
    items = tuple(unique.values())
    ids = list(unique)

    stored = (
        {row.hn_id: row for row in HNComment.objects.filter(hn_id__in=ids)}
        if ids
        else {}
    )
    existing = {
        hn_id: row for hn_id, row in stored.items() if row.thread_id == thread.pk
    }
    stats = CommentWriteStats(rows=dict(existing))

    created: list[HNComment] = []
    touched: list[HNComment] = []
    moved: list[HNComment] = []

    for item in items:
        values: dict[str, Any] = {
            "parent_hn_id": item.parent_hn_id,
            "depth": item.depth,
            "sibling_index": item.sibling_index,
            "path": item.path,
            "author": item.author,
            "text_html": item.text.html,
            "text_plain": item.text.text,
            "is_deleted": item.is_deleted,
            "is_dead": item.is_dead,
            "points": item.points,
            "posted_at": item.posted_at,
        }
        row = stored.get(item.hn_id)

        if row is None:
            row = HNComment(
                thread=thread,
                hn_id=item.hn_id,
                first_seen_at=synced_at,
                last_synced_at=synced_at,
                **values,
            )
            created.append(row)
            stats.rows[item.hn_id] = row
            stats.created += 1
            continue

        if row.thread_id != thread.pk:
            # HN moved this comment to the story whose tree we just fetched.
            # Ownership changed, so it counts as an update rather than an
            # unchanged row; `reassigned` keeps the move visible on its own.
            previous_thread_id = row.thread_id
            row.thread = thread
            _apply(row, values)
            row.last_synced_at = synced_at
            moved.append(row)
            stats.rows[item.hn_id] = row
            stats.updated += 1
            stats.reassigned += 1
            logger.warning(
                "Hacker News comment %s moved from thread %s to thread %s",
                item.hn_id,
                previous_thread_id,
                thread.pk,
            )
            continue

        changed = _apply(row, values)
        row.last_synced_at = synced_at
        touched.append(row)
        if changed:
            stats.updated += 1
        else:
            stats.unchanged += 1

    value_fields = [
        "parent_hn_id",
        "depth",
        "sibling_index",
        "path",
        "author",
        "text_html",
        "text_plain",
        "is_deleted",
        "is_dead",
        "points",
        "posted_at",
    ]

    if created:
        HNComment.objects.bulk_create(created)
    if moved:
        # Flush the reassignment before the pk map is re-read below, or a moved
        # parent would not be found and its child's FK would be nulled.
        HNComment.objects.bulk_update(
            moved, [*value_fields, "last_synced_at", "thread_id"]
        )
        # The old thread no longer owns these comments, so tags describing that
        # ownership are stale. Title-level tags have `comment=NULL` and survive.
        DiscussionTag.objects.filter(
            comment_id__in=[row.pk for row in moved]
        ).delete()
    if touched:
        HNComment.objects.bulk_update(touched, [*value_fields, "last_synced_at"])

    # `parent_hn_id` arrived with the payload, so the FK is derived from data we
    # already hold. Read the mapping back rather than relying on `bulk_create`
    # populating pks, which is backend-dependent.
    pk_by_hn_id = dict(
        HNComment.objects.filter(thread=thread).values_list("hn_id", "pk")
    )
    re_parented: list[HNComment] = []
    for item in items:
        row = stats.rows.get(item.hn_id)
        if row is None:  # pragma: no cover -- every parsed comment is in the map
            continue
        desired = (
            pk_by_hn_id.get(item.parent_hn_id) if item.parent_hn_id is not None else None
        )
        if row.parent_id != desired:
            row.parent_id = desired
            re_parented.append(row)

    if re_parented:
        HNComment.objects.bulk_update(re_parented, ["parent_id"])

    return stats


def replace_title_tags(
    thread: HNThread,
    tags: Sequence[tuple[None, ProviderEntity, str, str, int]],
    *,
    synced_at: datetime,
) -> int:
    """Rebuild a thread's title-level tags.

    Deletes only the tags whose `comment` is null, so it composes with
    `replace_comment_tags` rather than fighting it. Splitting them is what lets
    the title be re-tagged on **every** run -- it costs one matcher call per thread
    -- while comment tags are rebuilt only when the tree was refetched. Without the
    split, a thread whose tree was not fetched this hour would carry no tags at
    all, not even the one its own title earned.
    """
    thread.tags.filter(comment__isnull=True).delete()
    return _create_tags(thread, tags, synced_at=synced_at)


def replace_comment_tags(
    thread: HNThread,
    tags: Sequence[tuple[HNComment | None, ProviderEntity, str, str, int]],
    *,
    synced_at: datetime,
) -> int:
    """Rebuild a thread's per-comment tags, leaving the title's alone.

    Deleted and recreated rather than merged, because a tag is **derived** data --
    the same standing `ModelMatch` has, and the same exception the no-DELETE rule
    already makes for it. Rebuilding means a tag whose alias was withdrawn cannot
    linger, which a merge would leave behind with no way to notice.

    Called only for threads whose tree was fetched, so a change to a *comment*
    tag's alias reaches an existing thread through
    `manage.py refresh_discussions --skip-discovery`, which forces the refetch.
    Rebuilding every stored thread's comment tags on every hourly run instead would
    mean loading a few hundred thousand comment rows into memory each hour to redo
    work that had not changed.

    **A consequence worth knowing before editing the vocabulary:** deleting a
    `ProviderEntity` cascades its tags away, and the next run only rebuilds them
    for threads it refetches. So withdrawing an entity in the admin silently
    un-tags the stored comments that named it -- until each thread's comment count
    moves, or `--skip-discovery` is run once. That is the same boundary as an
    alias edit, arrived at through the FK rather than through the matcher.
    """
    thread.tags.filter(comment__isnull=False).delete()
    return _create_tags(thread, tags, synced_at=synced_at)


def _create_tags(thread, tags, *, synced_at: datetime) -> int:
    rows = [
        DiscussionTag(
            thread=thread,
            comment=comment,
            entity=entity,
            matched_text=matched_text[:120],
            match_mode=mode,
            mentions=mentions,
            first_seen_at=synced_at,
            last_synced_at=synced_at,
        )
        for comment, entity, matched_text, mode, mentions in tags
    ]
    if rows:
        DiscussionTag.objects.bulk_create(rows)
    return len(rows)


def prune_out_of_policy(
    *,
    cutoff: datetime,
    min_points: int,
    min_comments: int,
    stats: UpsertStats,
) -> tuple[int, int]:
    """Delete threads the retention policy no longer covers. Returns `(total, below_floor)`.

    Two ways out of the bank, and they are the same question asked twice -- "is
    this thread still something we keep?":

    * **Too old.** Older than the retention window.
    * **Below the floor.** Fewer points or fewer comments than the bar, or a
      comment count Hacker News does not report. Applying the floor here rather
      than only at discovery is what keeps the floors *the retention policy*
      instead of a rule consulted once: a reviewer who raises them sees the bank
      follow, and the run reports how much moved under `threads_below_floor`.

    The floor passed in is the **sweep's**, deliberately, not the window's. The
    window floor answers "is this one of the notable stories of the period?" and
    belongs to discovery; raising it should change what is *found*, not silently
    empty what is already stored. The sweep floor answers "is this a real
    discussion rather than trivia?", which is the bar worth holding a stored row to.

    The one DELETE against a source table in this app -- see the section header for
    why a Hacker News thread's loss is recoverable when a model row's is not.
    `comments` and `tags` follow by `on_delete=CASCADE`, in the caller's
    transaction, so a dry run rolls the whole thing back.

    Counted into `records_deactivated`, which for this source means "removed from
    the served set" rather than "flagged inactive" -- the column is the
    source-neutral removal counter, and inventing a parallel one would leave
    `/metadata/`'s per-run counters unable to describe an HN run.
    """
    doomed = HNThread.objects.filter(
        Q(posted_at__lt=cutoff)
        | Q(points__lt=min_points)
        | Q(num_comments__lt=min_comments)
        # A thread with no reported count cannot be shown to clear the floor, so it
        # does not stay. `num_comments__lt` is NULL for such a row and SQL NULL
        # comparisons are never true, which is why this needs saying separately.
        | Q(num_comments__isnull=True)
    )
    below_floor = doomed.filter(posted_at__gte=cutoff).count()
    total = doomed.count()
    if total:
        doomed.delete()
    stats.deactivated += total
    return total, below_floor
