"""Refresh orchestration -- the only place the five layers meet.

This module deliberately contains no parsing rules, no SQL and no HTTP details.
It sequences: fetch (network, outside any transaction) -> parse and dedupe
(pure) -> match (pure) -> write (one transaction) -> record the run.

**"Don't destroy the last good data", as five enforceable rules:**

1. No `DELETE` against a source table exists anywhere in the app. A model that
   vanished upstream is deactivated, so the previous state stays inspectable.
2. All writes for one source happen in a single `transaction.atomic()`. Network
   I/O never happens inside a transaction, so the SQLite write lock is held for
   milliseconds rather than for the length of a dataset download.
3. A failed run records `failed` plus `error_code` and touches no data. The rows
   from the last good run remain, and `last_success_at` still reports it --
   success and freshness are never conflated.
4. `deactivate_missing` runs only on a fully successful, non-empty fetch. A
   partial or empty response must never be able to blank the board; this is the
   specific failure mode the rule exists to prevent.
5. A 200 carrying zero models raises, rather than being treated as an empty
   catalogue. See `EmptyResponseError`.

**Sequencing.** `refresh_all()` runs LMArena first, then AA, in-process rather
than via `.delay()`. AA retention (`is_retained`) and the AA <-> agent match both
depend on agent entries written moments earlier; dispatching them as independent
tasks would let AA read a stale agent set and silently mis-retain models.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable

from django.conf import settings
from django.db import IntegrityError, transaction

from .. import persistence as store
from ..clients.artificial_analysis import DEFAULT_BASE_URL, ArtificialAnalysisClient
from ..clients.exceptions import EmptyResponseError, SourceError
from ..clients.lmarena import LMArenaClient, LoadedSplit
from ..constants import (
    CATEGORIES,
    INTERSECTED_CATEGORIES,
    PRIMARY_CATEGORY,
    Source,
    SyncStatus,
    UnmatchedReason,
)
from ..locking import run_lock
from ..matching import (
    AliasTable,
    Claim,
    MatchIndex,
    dedupe_by_model_key,
    match_aa_model,
    match_lmarena_key,
    resolve_collisions,
)
from ..models import LMArenaEntry, ModelAlias, SyncRun
from ..normalization import normalize_model_key
from ..persistence import UnmatchedLedger, UpsertStats
from ..validation import ValidationError, parse_aa_model, parse_lmarena_row

logger = logging.getLogger(__name__)

#: Lock scope used by `refresh_all`, which serialises both sources together.
ALL_SOURCES_LOCK = "all"

#: A `running` row older than this is assumed to belong to a dead worker.
STALE_RUNNING_SECONDS = 6 * 3600

# Which ledger owns which reasons. Each (source, reason) pair appears in exactly
# one set, so no phase can close out another phase's rows as stale. The split is
# by *knowability*, not by source: `no_aa_match` is a fact about an LMArena row
# that only the AA phase can establish, which is why it lives in its own set
# rather than alongside the other LMArena reasons.
LMARENA_LEDGER_REASONS: tuple[str, ...] = (
    UnmatchedReason.NOT_IN_AGENT_SET.value,
    UnmatchedReason.AMBIGUOUS_MATCH.value,
    UnmatchedReason.DUPLICATE_MODEL_NAME.value,
    UnmatchedReason.VALIDATION_FAILED.value,
    UnmatchedReason.MISSING_IDENTITY.value,
)

AA_LEDGER_REASONS: tuple[str, ...] = (
    UnmatchedReason.NO_LMARENA_MATCH.value,
    UnmatchedReason.AMBIGUOUS_MATCH.value,
    UnmatchedReason.DUPLICATE_MODEL_NAME.value,
    UnmatchedReason.VALIDATION_FAILED.value,
    UnmatchedReason.MISSING_IDENTITY.value,
)

AGENT_MISS_LEDGER_REASONS: tuple[str, ...] = (UnmatchedReason.NO_AA_MATCH.value,)


# --------------------------------------------------------------------------- #
# Settings accessors
# --------------------------------------------------------------------------- #


def _harness_fold_enabled() -> bool:
    return bool(getattr(settings, "LEADERBOARD_ENABLE_HARNESS_FOLD", True))


def build_aa_client(**overrides: Any) -> ArtificialAnalysisClient:
    """Construct the AA client from settings.

    A missing `AA_API_KEY` is deliberately not an error at construction time:
    `.configured` simply reports False and `fetch_all_models` raises
    `AuthenticationError`, which fails the AA refresh alone. The read-only API
    keeps serving whatever data is already stored, so a frontend developer can
    run the server before they have a key.
    """
    return ArtificialAnalysisClient(
        getattr(settings, "AA_API_KEY", ""),
        base_url=getattr(settings, "AA_BASE_URL", "") or DEFAULT_BASE_URL,
        **overrides,
    )


def build_lmarena_client(**overrides: Any) -> LMArenaClient:
    return LMArenaClient(**overrides)


# --------------------------------------------------------------------------- #
# Run bookkeeping helpers
# --------------------------------------------------------------------------- #


def _counters(stats: UpsertStats) -> dict[str, int]:
    return {
        "records_seen": stats.seen,
        "records_created": stats.created,
        "records_updated": stats.updated,
        "records_unchanged": stats.unchanged,
        "records_deactivated": stats.deactivated,
        "records_failed": stats.failed,
        "records_deduplicated": stats.deduplicated,
        "anomalies_recorded": stats.anomalies,
    }


def _skipped(
    source: str,
    *,
    triggered_by: str,
    dry_run: bool,
    celery_task_id: str,
    code: str,
    message: str,
) -> SyncRun:
    """Record "we chose not to run" as its own outcome.

    A skip is neither a success nor a failure: it must not refresh
    `last_success_at`, and it must not look like an error either. The frontend
    reads it as "still running" and keeps showing the previous data.
    """
    now = store.utcnow()
    return SyncRun.objects.create(
        source=source,
        status=SyncStatus.SKIPPED.value,
        triggered_by=triggered_by,
        dry_run=dry_run,
        celery_task_id=celery_task_id,
        started_at=now,
        finished_at=now,
        duration_ms=0,
        error_code=code,
        error_message=message,
    )


def _claim_run(
    source: str,
    *,
    triggered_by: str,
    dry_run: bool,
    celery_task_id: str,
) -> SyncRun | None:
    """Open a `running` row, or `None` when one is already open for this source.

    `None` means the conditional unique index fired -- the database-level
    overlap lock, which is the backstop for when Redis is unreachable and
    `run_lock` had to degrade to "acquired".
    """
    try:
        # A nested atomic block makes the IntegrityError recoverable rather than
        # poisoning the outer transaction.
        with transaction.atomic():
            return store.open_run(
                source,
                triggered_by=triggered_by,
                dry_run=dry_run,
                celery_task_id=celery_task_id,
            )
    except IntegrityError:
        return None


# --------------------------------------------------------------------------- #
# LMArena
# --------------------------------------------------------------------------- #


def refresh_lmarena(
    *,
    triggered_by: str = "cli",
    dry_run: bool = False,
    use_lock: bool = True,
    celery_task_id: str = "",
    synced_at: datetime | None = None,
    client: LMArenaClient | None = None,
) -> SyncRun:
    """Ingest all four LMArena categories. Never raises; returns the run."""
    source = Source.LMARENA.value
    synced_at = synced_at or store.utcnow()
    store.reap_stale_running(source, older_than_seconds=STALE_RUNNING_SECONDS)

    with run_lock(source, enabled=use_lock) as acquired:
        if not acquired:
            return _skipped(
                source,
                triggered_by=triggered_by,
                dry_run=dry_run,
                celery_task_id=celery_task_id,
                code="already_running",
                message="Another LMArena refresh holds the lock; skipping rather than queuing.",
            )

        run = _claim_run(
            source,
            triggered_by=triggered_by,
            dry_run=dry_run,
            celery_task_id=celery_task_id,
        )
        if run is None:
            return _skipped(
                source,
                triggered_by=triggered_by,
                dry_run=dry_run,
                celery_task_id=celery_task_id,
                code="already_running",
                message="A previous LMArena run is still marked running.",
            )

        try:
            return _execute_lmarena(
                run,
                client=client if client is not None else build_lmarena_client(),
                synced_at=synced_at,
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001 -- the run row must always close
            logger.exception("LMArena refresh failed")
            return store.fail_run(run, exc)


def _execute_lmarena(
    run: SyncRun,
    *,
    client: LMArenaClient,
    synced_at: datetime,
    dry_run: bool,
) -> SyncRun:
    # -- 1. Fetch (network; outside every transaction) ---------------------- #
    loaded: dict[str, LoadedSplit] = {}
    fields_failed: dict[str, str] = {}

    for category in CATEGORIES:
        try:
            loaded[category] = client.fetch_category(category)
        except SourceError as exc:
            fields_failed[category] = f"{exc.code}: {exc}"
            if category == PRIMARY_CATEGORY:
                # `agent` anchors every intersection and the whole joined
                # surface. Without it there is nothing to intersect against, so
                # this aborts the run before a single row is written.
                raise

    # -- 2. Parse and dedupe (pure) ----------------------------------------- #
    parsed: dict[str, list[Any]] = {}
    anomalies: list[dict[str, Any]] = []
    failed_rows = 0

    for category, split in loaded.items():
        rows = []
        for raw in split.rows:
            try:
                rows.append(parse_lmarena_row(raw, category))
            except ValidationError as exc:
                failed_rows += 1
                anomalies.append(
                    {
                        "reason": UnmatchedReason.VALIDATION_FAILED.value,
                        "category": category,
                        "model_key": normalize_model_key(str(raw.get("model_name") or "")),
                        "model_name": str(raw.get("model_name") or ""),
                        "detail": {"error": str(exc), "field": exc.field},
                    }
                )
        parsed[category] = rows

    deduped: dict[str, list[Any]] = {}
    #: Rows collapsed away by dedupe. `webdev` alone repeats 127 real models
    #: across 535 rows, so this is a large, meaningful number -- not bookkeeping.
    collapsed = 0
    for category, rows in parsed.items():
        winners, losers = dedupe_by_model_key(rows)
        deduped[category] = winners
        collapsed += len(losers)
        for loser, winner in losers:
            anomalies.append(
                {
                    "reason": UnmatchedReason.DUPLICATE_MODEL_NAME.value,
                    "category": category,
                    "model_key": loser.model_key,
                    "model_name": loser.model_name,
                    "organization": loser.organization,
                    "detail": {
                        "kept_name": winner.model_name,
                        "kept_rank": winner.rank,
                        "dropped_rank": loser.rank,
                    },
                }
            )

    if not deduped.get(PRIMARY_CATEGORY):
        # Rule 5: an empty agent split is a bad response, not an empty board.
        raise EmptyResponseError(
            "LMArena agent split produced no usable rows; refusing to treat this "
            "as an empty leaderboard"
        )

    # -- 3. Resolve the agent set (pure + one read-only alias lookup) -------- #
    agent_index = MatchIndex(enable_harness_fold=_harness_fold_enabled())
    for row in deduped[PRIMARY_CATEGORY]:
        agent_index.add(row.model_key, row)

    aliases = AliasTable(ModelAlias.objects.all())

    # `agent` rows are trivially members of their own set.
    agent_key_by_category: dict[str, dict[str, str]] = {
        PRIMARY_CATEGORY: {row.model_key: row.model_key for row in deduped[PRIMARY_CATEGORY]}
    }

    for category in INTERSECTED_CATEGORIES:
        mapping: dict[str, str] = {}
        for row in deduped.get(category, ()):
            outcome = match_lmarena_key(
                agent_index,
                row.model_name,
                alias_table=aliases,
                category=category,
            )
            if outcome.is_match:
                # `matched_key` differs from `row.model_key` exactly when the
                # harness fold applied -- recording it is what makes the folded
                # rows findable from the overview.
                mapping[row.model_key] = outcome.matched_key
                continue
            mapping.pop(row.model_key, None)
            anomalies.append(
                {
                    "reason": _cross_category_reason(outcome.status),
                    "category": category,
                    "model_key": row.model_key,
                    "model_name": row.model_name,
                    "organization": row.organization,
                    "detail": {**outcome.detail, "agent_key": outcome.matched_key},
                }
            )
        agent_key_by_category[category] = mapping

    # -- 4. Write (one transaction) ----------------------------------------- #
    stats = UpsertStats()
    stats.failed = failed_rows
    stats.deduplicated = collapsed
    ledger = UnmatchedLedger(
        Source.LMARENA.value, synced_at=synced_at, reasons=LMARENA_LEDGER_REASONS
    )

    with transaction.atomic():
        for category, rows in deduped.items():
            store.upsert_lmarena_entries(
                rows,
                agent_key_by_model_key=agent_key_by_category.get(category, {}),
                synced_at=synced_at,
                stats=stats,
            )

        # Rule 4: only a category we read completely *and* non-emptily may
        # deactivate anything. `deduped` holds exactly the categories that
        # loaded, so a failed field is automatically excluded.
        for category, rows in deduped.items():
            if rows:
                stats.deactivated += store.deactivate_missing_lmarena_entries(
                    category,
                    [row.model_key for row in rows],
                    synced_at=synced_at,
                )

        for anomaly in anomalies:
            ledger.record(**anomaly)
        stats.anomalies = len(anomalies)
        ledger.close_stale()

        if dry_run:
            transaction.set_rollback(True)

    revision = next((split.revision for split in loaded.values() if split.revision), "")

    # Hand the agent rows to a caller that is dry-running the pair. The AA run
    # needs them to match against, and a rolled-back transaction leaves nothing
    # in the database for it to find. Transient instance attribute, never stored.
    run.agent_rows_for_matching = list(deduped[PRIMARY_CATEGORY])

    return store.finish_run(
        run,
        SyncStatus.PARTIAL.value if fields_failed else SyncStatus.SUCCESS.value,
        fields_succeeded=sorted(loaded),
        fields_failed=fields_failed,
        dataset_revision=revision,
        summary={
            "agent_models": len(agent_index),
            "entries": {category: len(rows) for category, rows in deduped.items()},
            "in_agent_set": {
                category: len(mapping) for category, mapping in agent_key_by_category.items()
            },
        },
        **_counters(stats),
    )


def _cross_category_reason(status: str) -> str:
    """A miss inside a non-agent category is "not in the agent set", not "no
    LMArena match" -- the record *is* LMArena data, it just has no agent row."""
    if status == "ambiguous":
        return UnmatchedReason.AMBIGUOUS_MATCH.value
    if status == "missing_identity":
        return UnmatchedReason.MISSING_IDENTITY.value
    return UnmatchedReason.NOT_IN_AGENT_SET.value


# --------------------------------------------------------------------------- #
# Artificial Analysis
# --------------------------------------------------------------------------- #


def refresh_aa(
    *,
    triggered_by: str = "cli",
    dry_run: bool = False,
    use_lock: bool = True,
    celery_task_id: str = "",
    synced_at: datetime | None = None,
    client: ArtificialAnalysisClient | None = None,
    agent_rows: Iterable[Any] | None = None,
) -> SyncRun:
    """Ingest the AA free-tier catalogue. Never raises; returns the run.

    `agent_rows` supplies the agent set to match against instead of reading it
    from the database. Only `refresh_all` passes it, and only on a dry run,
    where the LMArena transaction has just rolled back and left nothing behind.
    """
    source = Source.ARTIFICIAL_ANALYSIS.value
    synced_at = synced_at or store.utcnow()
    store.reap_stale_running(source, older_than_seconds=STALE_RUNNING_SECONDS)

    with run_lock(source, enabled=use_lock) as acquired:
        if not acquired:
            return _skipped(
                source,
                triggered_by=triggered_by,
                dry_run=dry_run,
                celery_task_id=celery_task_id,
                code="already_running",
                message="Another AA refresh holds the lock; skipping rather than queuing.",
            )

        run = _claim_run(
            source,
            triggered_by=triggered_by,
            dry_run=dry_run,
            celery_task_id=celery_task_id,
        )
        if run is None:
            return _skipped(
                source,
                triggered_by=triggered_by,
                dry_run=dry_run,
                celery_task_id=celery_task_id,
                code="already_running",
                message="A previous AA run is still marked running.",
            )

        try:
            return _execute_aa(
                run,
                client=client if client is not None else build_aa_client(),
                synced_at=synced_at,
                dry_run=dry_run,
                agent_rows=agent_rows,
            )
        except Exception as exc:  # noqa: BLE001 -- the run row must always close
            logger.exception("Artificial Analysis refresh failed")
            return store.fail_run(run, exc)


def _execute_aa(
    run: SyncRun,
    *,
    client: ArtificialAnalysisClient,
    synced_at: datetime,
    dry_run: bool,
    agent_rows: Iterable[Any] | None = None,
) -> SyncRun:
    # -- 0. Preflight quota check ------------------------------------------- #
    blocking = _quota_exhausted()
    if blocking is not None:
        # Skipping here costs nothing and saves an HTTP call that is certain to
        # be refused. The previous data stays exactly as it is.
        return store.finish_run(
            run,
            SyncStatus.SKIPPED.value,
            error_code="rate_limit_exceeded",
            error_message=(
                "Previous AA run reported zero remaining quota; skipping until the "
                f"window resets at {blocking.rate_limit_reset_at:%Y-%m-%dT%H:%M:%SZ}."
            ),
            rate_limit_limit=blocking.rate_limit_limit,
            rate_limit_remaining=blocking.rate_limit_remaining,
            rate_limit_reset_at=blocking.rate_limit_reset_at,
            tier=blocking.tier,
        )

    # -- 1. Fetch (network; outside every transaction) ---------------------- #
    result = client.fetch_all_models()

    # -- 2. Parse (pure) ---------------------------------------------------- #
    parsed = []
    anomalies: list[dict[str, Any]] = []
    for raw in result.records:
        try:
            parsed.append(
                parse_aa_model(
                    raw,
                    intelligence_index_version=result.intelligence_index_version,
                )
            )
        except ValidationError as exc:
            anomalies.append(
                {
                    "reason": UnmatchedReason.VALIDATION_FAILED.value,
                    "category": PRIMARY_CATEGORY,
                    "model_key": normalize_model_key(str(raw.get("slug") or raw.get("id") or "")),
                    "model_name": str(raw.get("name") or ""),
                    "detail": {"error": str(exc), "field": exc.field},
                }
            )

    if not parsed:
        raise EmptyResponseError(
            "Every AA record failed validation; refusing to treat this as an empty "
            "catalogue",
            detail={"records_fetched": len(result.records)},
        )

    # -- 3. Match against the agent set (pure + one read-only alias lookup) -- #
    # `agent_rows` is the dry-run path: the caller's LMArena transaction rolled
    # back, so the database has no agent entries to read.
    in_memory_agent_set = agent_rows is not None
    if in_memory_agent_set:
        index_source = list(agent_rows or ())
    else:
        index_source = list(
            LMArenaEntry.objects.filter(category=PRIMARY_CATEGORY, is_active=True)
        )

    index = MatchIndex(enable_harness_fold=_harness_fold_enabled())
    for item in index_source:
        index.add(item.model_key, item)

    aliases = AliasTable(ModelAlias.objects.all())

    claims: list[Claim] = []
    unmatched: list[tuple[Any, Any]] = []
    for record in parsed:
        outcome = match_aa_model(
            index,
            name=record.name,
            slug=record.slug,
            alias_table=aliases,
        )
        if outcome.is_match:
            claims.append(
                Claim(
                    matched_key=outcome.matched_key,
                    method=outcome.method,
                    model=record,
                    name=record.name,
                    slug=record.slug,
                )
            )
        else:
            unmatched.append((record, outcome))

    winners, losers = resolve_collisions(claims)

    # `is_retained` marks membership in the agent subset. Collision losers are
    # members too -- they simply lost the single `ModelMatch` slot -- so they
    # stay retained and visible on `/artificial-analysis/`, reported as
    # duplicates rather than quietly un-retained.
    retained_aa_ids = {claim.model.aa_id for claim in winners.values()}
    retained_aa_ids.update(loser.model.aa_id for loser, _ in losers)

    creators: dict[str, str] = {}
    for record in parsed:
        if record.creator_aa_id:
            creators[record.creator_aa_id] = record.creator_name or record.creator_aa_id

    # -- 4. Write (one transaction) ----------------------------------------- #
    stats = UpsertStats()
    ledger = UnmatchedLedger(
        Source.ARTIFICIAL_ANALYSIS.value, synced_at=synced_at, reasons=AA_LEDGER_REASONS
    )
    # The other direction: agent models this catalogue did not resolve to. It is
    # an LMArena-sourced row, but only this phase can know it -- see
    # `LMARENA_LEDGER_REASONS` for why that forces a second ledger.
    agent_ledger = UnmatchedLedger(
        Source.LMARENA.value,
        synced_at=synced_at,
        reasons=AGENT_MISS_LEDGER_REASONS,
    )
    # `winners` is keyed by the agent key each surviving claim resolved to, so
    # "agent keys with no claim" is set difference against the index.
    claimed_keys = set(winners)
    agent_misses = [item for item in index_source if item.model_key not in claimed_keys]

    with transaction.atomic():
        creator_objects = store.upsert_creators(creators, synced_at=synced_at)
        models_by_aa_id = store.upsert_aa_models(
            parsed,
            creators=creator_objects,
            retained_aa_ids=retained_aa_ids,
            synced_at=synced_at,
            stats=stats,
        )

        # Skipped on the in-memory path: there are no agent rows in the database
        # to link against, and every claim would be counted as a failure. The
        # match outcome is still reported, via `summary` below.
        if not in_memory_agent_set:
            entries_by_key = {
                entry.model_key: entry
                for entry in LMArenaEntry.objects.filter(category=PRIMARY_CATEGORY)
            }
            store.rebuild_matches(
                list(winners.values()),
                entries_by_key,
                models_by_aa_id,
                synced_at=synced_at,
                stats=stats,
            )

        # Rule 4: reached only after a complete read, and `fetch_all_models`
        # raises rather than returning a partial catalogue.
        stats.deactivated += store.deactivate_missing_aa_models(
            (record.aa_id for record in parsed),
            synced_at=synced_at,
        )

        for record, outcome in unmatched:
            ledger.record(
                reason=outcome.reason,
                category=PRIMARY_CATEGORY,
                model_key=normalize_model_key(record.name) or normalize_model_key(record.slug),
                model_name=record.name,
                detail={**outcome.detail, "slug": record.slug},
            )
        for loser, winner in losers:
            ledger.record(
                reason=UnmatchedReason.DUPLICATE_MODEL_NAME.value,
                category=PRIMARY_CATEGORY,
                model_key=loser.matched_key,
                model_name=loser.name,
                detail={
                    "kept_name": winner.name,
                    "kept_slug": winner.slug,
                    "dropped_name": loser.name,
                    "dropped_slug": loser.slug,
                },
            )
        # Every agent model left without a claim is a row the completeness rule
        # will drop from `/overview/`, so it is recorded by name: this is the
        # list a human works through to decide between "AA simply lacks it" and
        # "our normalizer needs an alias here". `aa_records_considered` is what
        # makes that judgement sound -- it records that the comparison ran
        # against a *complete* catalogue read, not a partial one.
        for item in agent_misses:
            agent_ledger.record(
                reason=UnmatchedReason.NO_AA_MATCH.value,
                category=PRIMARY_CATEGORY,
                model_key=item.model_key,
                model_name=getattr(item, "model_name", "") or item.model_key,
                organization=getattr(item, "organization", "") or "",
                detail={
                    "rank": getattr(item, "rank", None),
                    "aa_records_considered": len(parsed),
                },
            )

        for anomaly in anomalies:
            ledger.record(**anomaly)

        stats.deduplicated = len(losers)
        stats.anomalies = len(anomalies) + len(unmatched) + len(losers)
        ledger.close_stale()
        agent_ledger.close_stale()

        if dry_run:
            transaction.set_rollback(True)

    return store.finish_run(
        run,
        SyncStatus.SUCCESS.value,
        tier=result.tier,
        intelligence_index_version=result.intelligence_index_version,
        page_size=result.page_size,
        total_pages=result.total_pages,
        pages_fetched=result.pages_fetched,
        rate_limit_limit=result.rate_limit.limit,
        rate_limit_remaining=result.rate_limit.remaining,
        rate_limit_reset_at=result.rate_limit.reset_at,
        summary={
            "agent_models": len(index),
            "aa_records": len(parsed),
            "matched": len(winners),
            "unmatched": len(unmatched),
            "agent_models_unmatched": len(agent_misses),
            "duplicates": len(losers),
            "matches_persisted": not in_memory_agent_set,
            "coverage_percent": (
                len(winners) * 100 // len(index) if len(index) else None
            ),
        },
        **_counters(stats),
    )


def _quota_exhausted() -> SyncRun | None:
    """The most recent AA run, when it proved the quota is spent.

    Returns the run whose `X-RateLimit-Remaining` was 0 and whose reset window
    has not yet passed, so the caller can skip without spending a request. Any
    ambiguity -- no timestamp, a stale window, a nonzero count -- returns `None`
    and the refresh proceeds normally.
    """
    run = (
        SyncRun.objects.filter(source=Source.ARTIFICIAL_ANALYSIS.value)
        .exclude(rate_limit_reset_at=None)
        .order_by("-started_at")
        .first()
    )
    if run is None or run.rate_limit_remaining != 0:
        return None
    if run.rate_limit_reset_at is not None and run.rate_limit_reset_at > store.utcnow():
        return run
    return None


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def refresh_all(
    *,
    triggered_by: str = "cli",
    dry_run: bool = False,
    use_lock: bool = True,
    celery_task_id: str = "",
    synced_at: datetime | None = None,
    lmarena_client: LMArenaClient | None = None,
    aa_client: ArtificialAnalysisClient | None = None,
) -> dict[str, SyncRun]:
    """Refresh both sources in dependency order.

    LMArena runs **first and in-process**, because AA's retention flag and its
    match against the agent set both depend on agent entries that must already
    exist. Dispatching them as independent Celery tasks would let AA read a
    stale agent set on a cold database and retain nothing.
    """
    synced_at = synced_at or store.utcnow()

    with run_lock(ALL_SOURCES_LOCK, enabled=use_lock) as acquired:
        if not acquired:
            return {
                source: _skipped(
                    source,
                    triggered_by=triggered_by,
                    dry_run=dry_run,
                    celery_task_id=celery_task_id,
                    code="already_running",
                    message="Another combined refresh holds the lock; skipping.",
                )
                for source in (Source.LMARENA.value, Source.ARTIFICIAL_ANALYSIS.value)
            }

        lmarena_run = refresh_lmarena(
            triggered_by=triggered_by,
            dry_run=dry_run,
            use_lock=False,
            celery_task_id=celery_task_id,
            synced_at=synced_at,
            client=lmarena_client,
        )

        # On a dry run the LMArena transaction has just rolled back, so the
        # database holds no agent entries for AA to match against. Hand the rows
        # over in memory instead -- otherwise `--dry-run --source=all` would
        # report a 0% match rate on a database that is merely empty, which reads
        # as a catastrophic regression rather than as an artifact of the rollback.
        carried = getattr(lmarena_run, "agent_rows_for_matching", None)

        aa_run = refresh_aa(
            triggered_by=triggered_by,
            dry_run=dry_run,
            use_lock=False,
            celery_task_id=celery_task_id,
            synced_at=synced_at,
            client=aa_client,
            agent_rows=carried if dry_run else None,
        )

        return {
            Source.LMARENA.value: lmarena_run,
            Source.ARTIFICIAL_ANALYSIS.value: aa_run,
        }
