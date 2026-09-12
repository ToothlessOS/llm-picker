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

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from .constants import SUCCESSFUL_STATUSES, SyncStatus
from .matching import Claim
from .models import (
    LLMModel,
    LMArenaEntry,
    ModelCreator,
    ModelMatch,
    SyncRun,
    UnmatchedRecord,
)
from .validation import ParsedAAModel, ParsedLMArenaRow


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
            confidence=1.0 if claim.rank <= 3 else 0.75,
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
