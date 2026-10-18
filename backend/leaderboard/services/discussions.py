"""Hacker News discussion refresh -- orchestration and transaction boundaries.

The same rules `refresh.py` enforces, applied to a source whose lifecycle differs
in one respect worth naming up front: **threads are pruned by age.**

Every other source here records measurements the project owns, so a row that
vanishes upstream is deactivated and never deleted -- our copy is the last one,
and the previous state has to stay inspectable. A Hacker News thread is the
opposite: `GET https://hn.algolia.com/api/v1/items/{id}` keeps serving it forever,
so an aged-out row is a re-fetchable cache entry. Age-based pruning is therefore
safe, and it is what lets membership be **monotonic** -- `posted_at` is immutable
and the cutoff only moves forward, so nothing can re-enter the bank. That single
property removes the need for an `is_active` flag, for a miss-counter suppressing
hysteresis at a rank boundary, and for a stored `is_top`.

Numbered, as in `refresh.py`, because these are the rules a reviewer checks:

1. Network I/O happens **outside every transaction**. A tree fetch takes seconds,
   and holding SQLite's write lock for that long would stall the API's reads.
2. All writes for one run happen in a **single** `transaction.atomic()`.
3. A failed run records `failed` + `error_code` and touches no data, so the
   previous hour's bank survives intact.
4. The prune is by age, which is independent of discovery completeness, so a
   partial discovery cannot blank the bank -- and a dry run rolls the prune back
   with everything else.
5. `EmptyResponseError` applies to the **window query only**. A single keyword
   matching nothing is the ordinary case and must never fail an hourly run.
6. Nothing raises out of `refresh_discussions`; it returns a `SyncRun` whose
   `status` says what happened.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable, Iterable, Sequence

from django.conf import settings
from django.db import transaction

from .. import persistence as store
from ..clients.exceptions import SourceError
from ..clients.hackernews import DEFAULT_BASE_URL, DiscoveryResult, HackerNewsClient
from ..constants import (
    HN_RELEVANCE_TERMS,
    HN_SWEEP_TERMS,
    SUCCESSFUL_STATUSES,
    Source,
    SyncStatus,
    hn_config,
)
from ..hn_matching import PhraseIndex, find_phrases, fired_relevance_terms, relevance_index
from ..hn_parsing import ParsedStoryHit, ParsedTree, parse_item_tree, parse_story_hit
from ..locking import run_lock
from ..models import HNComment, HNThread, ProviderAlias, ProviderEntity, SyncRun
from ..persistence import UpsertStats
from ..validation import ValidationError, as_int
from .runbook import (
    STALE_RUNNING_SECONDS,
    claim_run as _claim_run,
    counters as _counters,
    skipped as _skipped,
)

logger = logging.getLogger(__name__)

#: Discovery streams, recorded per thread in `source_metadata.discovered_by`.
STREAM_WINDOW = "window"
STREAM_KEYWORD = "keyword"
STREAM_MANUAL = "manual"

#: Seconds in a day, named so the window arithmetic reads as days.
SECONDS_PER_DAY = 86400


# --------------------------------------------------------------------------- #
# Settings accessors
# --------------------------------------------------------------------------- #


def hn_enabled() -> bool:
    return bool(getattr(settings, "LEADERBOARD_HN_ENABLED", True))


def build_hn_client(**overrides: Any) -> HackerNewsClient:
    """Construct the HN client from settings.

    No API key exists to be missing, so unlike `build_aa_client` there is no
    `configured` gate -- but the client is still built here rather than at module
    scope, which is what lets a test drive the whole pipeline by passing one in.
    """
    cfg = hn_config()
    return HackerNewsClient(
        base_url=getattr(settings, "LEADERBOARD_HN_BASE_URL", "") or DEFAULT_BASE_URL,
        tree_timeout=cfg.tree_timeout_seconds,
        hits_per_page=cfg.hits_per_page,
        max_page=cfg.max_page,
        max_item_bytes=cfg.max_item_bytes,
        max_inline_retry_after_seconds=cfg.max_inline_retry_after_seconds,
        **overrides,
    )


def skip_disabled(*, triggered_by: str = "celery:beat") -> SyncRun:
    """The run row written when `LEADERBOARD_HN_ENABLED` is false.

    Belt and braces, deliberately: `django-celery-beat`'s `DatabaseScheduler`
    materialises the schedule into `PeriodicTask` rows and the database is then
    authoritative, so deleting the entry from `CELERY_BEAT_SCHEDULE` does **not**
    stop the task firing. The setting therefore has to short-circuit inside the
    task as well.
    """
    return _skipped(
        Source.HACKERNEWS.value,
        triggered_by=triggered_by,
        dry_run=False,
        celery_task_id="",
        code="disabled",
        message="LEADERBOARD_HN_ENABLED is false; skipping the discussion refresh.",
    )


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EntityVocabulary:
    """The provider/service aliases, indexed for matching.

    `by_key` turns a matched phrase back into an entity. The phrase key *is* the
    alias key, so one dict lookup resolves a tag -- and because `alias_key` is
    unique across entities at the database level, a fired phrase can only ever
    mean one thing.
    """

    index: PhraseIndex
    by_key: dict[str, ProviderEntity]


def load_entity_vocabulary() -> EntityVocabulary:
    """Build the matcher's vocabulary from the reviewed alias table."""
    by_key: dict[str, ProviderEntity] = {}
    entries: list[tuple[str, str, str]] = []
    for alias in ProviderAlias.objects.select_related("entity").filter(
        entity__is_active=True
    ):
        entries.append((alias.alias_key, alias.match_mode, alias.alias_text))
        by_key.setdefault(alias.alias_key, alias.entity)
    return EntityVocabulary(index=PhraseIndex.build(entries), by_key=by_key)


@lru_cache(maxsize=1)
def _relevance_index() -> PhraseIndex:
    """The relevance vocabulary, built once per process.

    Cached because it is a pure function of a module constant and it is consulted
    for every story of every run -- and `lru_cache` rather than a module global so
    a test can clear it with `cache_clear()` instead of reaching into state.
    """
    return relevance_index(HN_RELEVANCE_TERMS)


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DiscoveredStory:
    """A story from the search API, and which streams found it."""

    story: ParsedStoryHit
    streams: list[str]


@dataclass(frozen=True)
class Candidate:
    """A story that survived the relevance filter, with why and how it ranks."""

    story: ParsedStoryHit
    terms: list[str]
    rank_score: float
    streams: list[str]


def window_slices(
    *,
    now: datetime,
    window_days: int,
    slice_days: int,
) -> list[tuple[int, int]]:
    """The retention window, split into pagination-safe slices.

    `hitsPerPage * page` cannot exceed 1,000 and past that the API returns a
    *plausible truncated* set, so one query covering a fortnight would silently
    lose its oldest -- and least replaceable -- days. Slicing keeps every retained
    day inside the ceiling.

    Newest slice first, so if a run is cut short the days it covered are the ones
    a reader is most likely to look at.
    """
    if slice_days < 1:
        raise ValueError("slice_days must be at least 1")
    newest = int(now.timestamp())
    oldest = newest - int(window_days) * SECONDS_PER_DAY
    slices: list[tuple[int, int]] = []
    cursor = newest
    while cursor > oldest:
        start = max(oldest, cursor - int(slice_days) * SECONDS_PER_DAY)
        slices.append((start, cursor))
        cursor = start
    return slices


def merge_hits(
    *,
    window: DiscoveryResult | None,
    sweeps: Sequence[DiscoveryResult],
) -> dict[int, DiscoveredStory]:
    """Dedupe hits across streams, recording which stream found each story.

    Keyed on the Algolia `objectID`, which is the HN item id -- the same identity
    the thread row is upserted on, so a story found by both the window query and a
    keyword sweep collapses to one entry rather than two.

    Unparseable hits are skipped rather than fatal: one malformed entry must not
    cost a whole window, and the count is visible in the run counters.
    """
    merged: dict[int, DiscoveredStory] = {}

    sources: list[tuple[DiscoveryResult | None, str]] = [(window, STREAM_WINDOW)]
    sources.extend((sweep, STREAM_KEYWORD) for sweep in sweeps)

    for result, stream in sources:
        if result is None:
            continue
        for hit in result.hits:
            try:
                story = parse_story_hit(hit)
            except ValidationError as exc:
                logger.debug("Skipping unparseable Hacker News hit: %s", exc)
                continue
            found = merged.get(story.hn_id)
            if found is None:
                merged[story.hn_id] = DiscoveredStory(story=story, streams=[stream])
            elif stream not in found.streams:
                found.streams.append(stream)

    for discovered in merged.values():
        discovered.streams.sort()
    return merged


def rank_score(story: ParsedStoryHit, *, comment_weight: float) -> float:
    """`points + weight * num_comments`.

    The draft asks for "up-votes / number of comments", and a comment is evidence
    of engagement, which is this feature's whole subject. Stored as a column so
    the read path can `ORDER BY` it, while both components stay separately
    orderable so a reader who disagrees with the weighting can re-rank without a
    deploy. An unreported count contributes nothing rather than being invented as
    a zero.
    """
    return float(story.points or 0) + float(comment_weight) * float(story.num_comments or 0)


def select_candidates(
    *,
    discovered: dict[int, DiscoveredStory],
    relevance: PhraseIndex,
    comment_weight: float,
    require_relevance: bool = True,
) -> tuple[list[Candidate], int]:
    """Filter stories to LLM-related ones and rank them. Returns `(candidates, dropped)`.

    A story that fires no relevance term is dropped outright rather than stored
    with a flag: the bank's contents *are* the served set, so an irrelevant row
    would be one the API has to filter out on every request just to hide it.

    `require_relevance=False` admits everything, for the manual path: an operator
    naming a thread with `--hn-id` has already decided it belongs, and silently
    discarding it because its title lacks a keyword would make the one tool for
    inspecting a specific story unable to load one. Such a thread simply carries
    no `relevance_terms`, which is the honest record of why it is there.
    """
    candidates: list[Candidate] = []
    dropped = 0

    for item in discovered.values():
        story = item.story
        terms = fired_relevance_terms(
            title=story.title, domain=story.domain, index=relevance
        )
        if not terms and require_relevance:
            dropped += 1
            continue
        candidates.append(
            Candidate(
                story=story,
                terms=terms,
                rank_score=rank_score(story, comment_weight=comment_weight),
                streams=item.streams,
            )
        )

    # Highest ranked first, deterministic on ties so two runs cannot disagree
    # about which threads the tree budget reaches.
    candidates.sort(key=lambda candidate: (-candidate.rank_score, -candidate.story.hn_id))
    return candidates, dropped


def keyword_cursor() -> int:
    """Where the previous successful run stopped sweeping.

    Carried in `SyncRun.summary` rather than in a table of its own: it is a
    *position*, not a fact, and losing it costs one repeated sweep rather than any
    correctness.
    """
    run = (
        SyncRun.objects.filter(
            source=Source.HACKERNEWS.value,
            status__in=SUCCESSFUL_STATUSES,
            dry_run=False,
        )
        .order_by("-started_at")
        .first()
    )
    if run is None:
        return 0
    try:
        return as_int((run.summary or {}).get("keyword_cursor")) or 0
    except ValidationError:
        # `as_int` refuses a value it cannot parse rather than guessing, which is
        # right everywhere else and wrong here: a corrupted cursor must cost one
        # repeated sweep, never the whole run.
        logger.warning("Discarding an unparseable keyword cursor from run %s", run.id)
        return 0


def sweep_terms(*, cursor: int, budget: int) -> tuple[list[str], int]:
    """The terms to sweep this run, and the cursor to store afterwards.

    Round-robin rather than the whole list: cost stays constant per hour however
    large the vocabulary grows, and every term is still swept every
    `len(terms) / budget` hours.
    """
    total = len(HN_SWEEP_TERMS)
    if total == 0:
        return [], 0
    if budget <= 0:
        return [], cursor % total
    start = cursor % total
    chosen = [HN_SWEEP_TERMS[(start + offset) % total] for offset in range(budget)]
    return chosen, (start + budget) % total


def _combine(first: DiscoveryResult, second: DiscoveryResult) -> DiscoveryResult:
    """Fold two slices into one result, so truncation is judged across the window."""
    return DiscoveryResult(
        hits=[*first.hits, *second.hits],
        pages_fetched=first.pages_fetched + second.pages_fetched,
        nb_hits=first.nb_hits + second.nb_hits,
    )


def run_discovery(
    client: HackerNewsClient,
    *,
    now: datetime,
    cursor: int,
) -> tuple[DiscoveryResult, list[DiscoveryResult], int]:
    """The sliced window query plus the budgeted keyword sweep.

    Returns ``(window, sweeps, next_cursor)``. The cursor is a *return value*
    rather than module state so a run is a pure function of its inputs -- which is
    what makes two runs in the same process independent.
    """
    cfg = hn_config()

    window: DiscoveryResult | None = None
    for start, end in window_slices(
        now=now, window_days=cfg.window_days, slice_days=cfg.window_slice_days
    ):
        result = client.search_window(
            start=start,
            end=end,
            min_points=cfg.min_points,
            min_comments=cfg.min_comments,
        )
        window = result if window is None else _combine(window, result)

    if window is None:  # pragma: no cover -- window_slices always yields one
        raise SourceError("Hacker News window produced no slices")

    terms, next_cursor = sweep_terms(cursor=cursor, budget=cfg.keyword_query_budget)
    since = int((now - timedelta(days=cfg.window_days)).timestamp())
    sweeps = [
        client.search_term(
            term=term,
            since=since,
            min_points=cfg.sweep_min_points,
            min_comments=cfg.sweep_min_comments,
        )
        for term in terms
    ]
    return window, sweeps, next_cursor


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def refresh_discussions(
    *,
    triggered_by: str = "cli",
    dry_run: bool = False,
    use_lock: bool = True,
    celery_task_id: str = "",
    synced_at: datetime | None = None,
    client: HackerNewsClient | None = None,
    hn_ids: Iterable[int] | None = None,
    skip_discovery: bool = False,
    keep_stale: bool = False,
    max_trees: int | None = None,
    now: datetime | None = None,
    monotonic: Callable[[], float] | None = None,
) -> SyncRun:
    """Refresh the Hacker News discussion bank. Never raises; returns the run.

    `hn_ids` fetches exactly those threads and skips discovery -- for an operator
    debugging one story. `skip_discovery` refetches the standing bank without
    asking the search API what exists. `keep_stale` suppresses the age-out prune,
    which is the only reason it exists.
    """
    source = Source.HACKERNEWS.value
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
                message="Another discussion refresh holds the lock; skipping rather than queuing.",
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
                message="A previous discussion run is still marked running.",
            )

        try:
            return _execute(
                run,
                client=client if client is not None else build_hn_client(),
                synced_at=synced_at,
                dry_run=dry_run,
                hn_ids=list(hn_ids) if hn_ids is not None else None,
                skip_discovery=skip_discovery,
                keep_stale=keep_stale,
                max_trees=max_trees,
                now=now or synced_at,
                monotonic=monotonic or time.monotonic,
            )
        except Exception as exc:  # noqa: BLE001 -- the run row must always close
            logger.exception("Hacker News discussion refresh failed")
            return store.fail_run(run, exc)


def _execute(
    run: SyncRun,
    *,
    client: HackerNewsClient,
    synced_at: datetime,
    dry_run: bool,
    hn_ids: list[int] | None,
    skip_discovery: bool,
    keep_stale: bool,
    max_trees: int | None,
    now: datetime,
    monotonic: Callable[[], float],
) -> SyncRun:
    cfg = hn_config()
    stats = UpsertStats()
    summary: dict[str, Any] = {}

    # -- 1. Discovery (network; outside every transaction) ------------------ #
    window: DiscoveryResult | None = None
    sweeps: list[DiscoveryResult] = []
    next_cursor = keyword_cursor()

    if hn_ids is not None:
        discovered = _discover_manual(client, hn_ids, stats=stats)
        summary["stream"] = "manual"
    elif skip_discovery:
        discovered = _discover_from_bank()
        summary["stream"] = "refresh-only"
    else:
        window, sweeps, next_cursor = run_discovery(client, now=now, cursor=next_cursor)
        discovered = merge_hits(window=window, sweeps=sweeps)

    raw_hits = sum(
        len(result.hits) for result in (window, *sweeps) if result is not None
    )
    stats.seen = len(discovered)
    stats.deduplicated = max(0, raw_hits - len(discovered))
    summary.update(
        {
            "window_hits": len(window.hits) if window else 0,
            "window_truncated": bool(window and window.truncated),
            "keyword_queries": sum(sweep.pages_fetched for sweep in sweeps),
            "keyword_cursor": next_cursor,
            "unique_stories": len(discovered),
        }
    )

    # -- 2. Relevance and ranking (pure) ------------------------------------ #
    # The manual paths admit anything: an operator naming a thread has decided it
    # belongs. See `select_candidates`.
    manual = hn_ids is not None or skip_discovery
    candidates, dropped = select_candidates(
        discovered=discovered,
        relevance=_relevance_index(),
        comment_weight=cfg.comment_weight,
        require_relevance=not manual,
    )
    summary["llm_related"] = len(candidates)
    summary["dropped_irrelevant"] = dropped

    # -- 3. Read-only lookups ----------------------------------------------- #
    existing = {
        thread.hn_id: thread
        for thread in HNThread.objects.only("hn_id", "num_comments", "fetched_at")
    }
    vocabulary = load_entity_vocabulary()
    summary["entities_with_aliases"] = len(vocabulary.by_key)

    # -- 4. Fetch trees (network; outside every transaction) ---------------- #
    budget = cfg.max_trees_per_run if max_trees is None else max_trees
    trees, tree_stats = _fetch_trees(
        client,
        candidates=candidates,
        existing=existing,
        cfg=cfg,
        budget=budget,
        monotonic=monotonic,
        force=manual,
    )
    stats.failed += tree_stats["trees_failed"]
    summary.update(tree_stats)

    # -- 5. Write (one transaction) ----------------------------------------- #
    cutoff = now - timedelta(days=cfg.window_days)
    pruned = 0
    comments_created = 0
    comments_updated = 0
    comments_unchanged = 0
    comments_reassigned = 0
    comments_stored = 0

    # Attached before the write phase so that a failure inside it still reports
    # what discovery saw. `fail_run` saves the instance, so anything set here
    # survives into the failed row -- and the alternative, an operator reading
    # "0 stories seen" after a write blew up 14 seconds in, hides the one piece of
    # context that would explain it.
    run.summary = dict(summary)

    with transaction.atomic():
        for candidate in candidates:
            thread, _ = store.upsert_hn_thread_discovery(
                candidate.story,
                terms=candidate.terms,
                rank_score=candidate.rank_score,
                discovered_by=candidate.streams,
                synced_at=synced_at,
                stats=stats,
            )
            # The title is re-tagged on every run, tree or no tree: it is one
            # matcher call, and skipping it would leave a thread whose tree was
            # deferred this hour with no tags at all.
            store.replace_title_tags(
                thread, build_title_tags(thread.title, vocabulary), synced_at=synced_at
            )

            tree = trees.get(candidate.story.hn_id)
            if tree is None:
                continue
            store.record_hn_tree(thread, tree, synced_at=synced_at)
            written = store.upsert_hn_comments(thread, tree.comments, synced_at=synced_at)
            comments_created += written.created
            comments_updated += written.updated
            comments_unchanged += written.unchanged
            comments_reassigned += written.reassigned
            comments_stored += len(tree.comments)
            store.replace_comment_tags(
                thread,
                build_comment_tags(tree, written.rows, vocabulary),
                synced_at=synced_at,
            )

        if not keep_stale and hn_ids is None:
            # Exempt when an operator named specific threads: pruning the story
            # they just asked to inspect is never what they wanted. Such a thread
            # is still pruned by the next scheduled run, so the exemption cannot
            # let the bank grow without bound.
            #
            # The floors passed are the *sweep's*, not the window's. That is what
            # keeps raising the window floor -- a discovery decision -- from
            # retroactively emptying the bank, while still making the sweep floor
            # the bar for what may remain.
            pruned, below_floor = store.prune_out_of_policy(
                cutoff=cutoff,
                min_points=cfg.sweep_min_points,
                min_comments=cfg.sweep_min_comments,
                stats=stats,
            )
            summary["threads_below_floor"] = below_floor

        if dry_run:
            transaction.set_rollback(True)

    summary["threads_pruned"] = pruned
    # Comment volume lives here rather than in the `SyncRun` counters, which
    # describe one population -- threads. Folding comments in would report
    # `records_created` above `records_seen`, because discovery only ever sees
    # stories.
    summary["comments_stored"] = comments_stored
    summary["comments_created"] = comments_created
    summary["comments_updated"] = comments_updated
    summary["comments_unchanged"] = comments_unchanged
    # Comments HN moved here from another story. Orthogonal to `updated`.
    summary["comments_reassigned"] = comments_reassigned

    return store.finish_run(
        run,
        SyncStatus.PARTIAL.value if tree_stats["trees_failed"] else SyncStatus.SUCCESS.value,
        summary=summary,
        **_counters(stats),
    )


# --------------------------------------------------------------------------- #
# Discovery paths
# --------------------------------------------------------------------------- #


def _discover_manual(
    client: HackerNewsClient,
    hn_ids: list[int],
    *,
    stats: UpsertStats,
) -> dict[int, DiscoveredStory]:
    """Stories for an explicit id list, fetched one at a time.

    The item endpoint rather than search, because an operator naming a thread
    means *that* thread, and search cannot address one by id.
    """
    discovered: dict[int, DiscoveredStory] = {}
    for hn_id in hn_ids:
        try:
            payload = client.fetch_item(hn_id)
            story = parse_story_hit(payload)
        except SourceError as exc:
            logger.warning("Could not fetch Hacker News item %s: %s", hn_id, exc)
            stats.failed += 1
            continue
        except ValidationError as exc:
            logger.warning("Hacker News item %s did not parse: %s", hn_id, exc)
            stats.failed += 1
            continue
        discovered[story.hn_id] = DiscoveredStory(story=story, streams=[STREAM_MANUAL])
    return discovered


def _discover_from_bank() -> dict[int, DiscoveredStory]:
    """The stories already stored, for `--skip-discovery`.

    Read back out of the database so a refresh-only run touches exactly the bank
    it already has rather than re-deciding what belongs in it.
    """
    discovered: dict[int, DiscoveredStory] = {}
    for thread in HNThread.objects.all():
        discovered[thread.hn_id] = DiscoveredStory(
            story=ParsedStoryHit(
                hn_id=thread.hn_id,
                title=thread.title,
                url=thread.url,
                domain=thread.domain,
                author=thread.author,
                points=thread.points,
                num_comments=thread.num_comments,
                posted_at=thread.posted_at,
                raw={},
            ),
            streams=[STREAM_WINDOW],
        )
    return discovered


# --------------------------------------------------------------------------- #
# Tree fetching
# --------------------------------------------------------------------------- #


#: Stands in for a `fetched_at` that has never been set. An aware epoch rather
#: than `None`, because a sort key cannot compare `None` against a datetime.
_NEVER_FETCHED = datetime.min.replace(tzinfo=timezone.utc)


def _staleness(candidate: Candidate, existing: dict[int, HNThread]) -> tuple[int, datetime]:
    """Sort key putting the least recently fetched tree first.

    A thread that has never been fetched sorts ahead of every dated one, which is
    what lets an operator's repeated forced runs reach the tail of the bank rather
    than looping over its top `budget` rows forever.
    """
    thread = existing.get(candidate.story.hn_id)
    if thread is None or thread.fetched_at is None:
        return (0, _NEVER_FETCHED)
    return (1, thread.fetched_at)


def _fetch_trees(
    client: HackerNewsClient,
    *,
    candidates: Sequence[Candidate],
    existing: dict[int, HNThread],
    cfg: Any,
    budget: int,
    monotonic: Callable[[], float],
    force: bool = False,
) -> tuple[dict[int, ParsedTree], dict[str, int]]:
    """Fetch the trees that are due, inside a request and a wall-clock budget.

    A tree is due when it has never been fetched, or when the story's reported
    comment count has moved since we last looked. That second condition is why the
    gate compares `num_comments` (what the *story* says) and not
    `comments_stored` (what we kept): a truncated thread keeps `comments_stored`
    below `num_comments` forever, so gating on that would refetch it every hour
    for the rest of its life.

    `force` bypasses the gate, and the manual paths need it rather than want it.
    `--skip-discovery` reads its stories *back out of the database*, so the
    `num_comments` it compares against is the one it just read -- the gate would
    report "unchanged" every time and the flag could never fetch anything at all.
    An operator asking for a refetch means it.

    When forcing, the **stalest trees go first** rather than the highest-ranked.
    That is what makes repeated forced runs sweep the whole bank instead of
    looping forever over its top `budget` rows: an operator applying a vocabulary
    change has to be able to reach the tail eventually, and ordering by
    `fetched_at` is the only ordering that guarantees it.

    Budgets rather than targets: whatever is not reached is deferred to the next
    hour and reported, because an hourly job that overran its own interval would
    collide with itself.
    """
    started = monotonic()
    trees: dict[int, ParsedTree] = {}
    stats = {
        "trees_fetched": 0,
        "trees_deferred": 0,
        "trees_failed": 0,
        "trees_skipped_oversize": 0,
        "trees_unchanged": 0,
    }

    if force:
        candidates = sorted(
            candidates, key=lambda candidate: _staleness(candidate, existing)
        )

    for candidate in candidates:
        story = candidate.story

        if story.num_comments is not None and story.num_comments > cfg.max_comments:
            # Refused before spending a request: a thread this large is megabytes
            # of JSON, and the tree endpoint has no way to ask for less than all
            # of it.
            stats["trees_skipped_oversize"] += 1
            continue

        stored = existing.get(story.hn_id)
        if not force and stored is not None and stored.fetched_at is not None:
            if stored.num_comments == story.num_comments:
                stats["trees_unchanged"] += 1
                continue

        if len(trees) >= budget or monotonic() - started > cfg.run_budget_seconds:
            stats["trees_deferred"] += 1
            continue

        try:
            payload = client.fetch_item(story.hn_id)
            tree = parse_item_tree(payload, max_stored_comments=cfg.max_stored_comments)
        except (SourceError, ValidationError) as exc:
            # One thread failing must not fail the run: the rest of the bank is
            # still good, so this counts a failure and the run finishes partial.
            logger.warning("Could not read Hacker News tree %s: %s", story.hn_id, exc)
            stats["trees_failed"] += 1
            continue

        trees[story.hn_id] = tree
        stats["trees_fetched"] += 1

    return trees, stats


# --------------------------------------------------------------------------- #
# Tagging
# --------------------------------------------------------------------------- #


def build_title_tags(
    title: str,
    vocabulary: EntityVocabulary,
) -> list[tuple[HNComment | None, ProviderEntity, str, str, int]]:
    """The entities a thread's title names.

    Built for **every** candidate on every run, whether or not its tree was
    fetched: a title is one string, so this is one matcher call per thread, and
    leaving it out would leave a thread whose tree was deferred this hour with no
    tags at all -- not even the one its own title earned.
    """
    return _tags_from(None, title, vocabulary)


def build_comment_tags(
    tree: ParsedTree,
    comment_rows: dict[int, HNComment],
    vocabulary: EntityVocabulary,
) -> list[tuple[HNComment | None, ProviderEntity, str, str, int]]:
    """The entities named in a thread's comments, aggregated per comment."""
    tags: dict[int, tuple[HNComment | None, ProviderEntity, str, str, int]] = {}
    for comment in tree.comments:
        row = comment_rows.get(comment.hn_id)
        if row is None:  # pragma: no cover -- every parsed comment has a row
            continue
        for tag in _tags_from(row, comment.text.text, vocabulary):
            tags[row.pk] = tag
    return list(tags.values())


def _tags_from(
    comment: HNComment | None,
    text: str,
    vocabulary: EntityVocabulary,
) -> list[tuple[HNComment | None, ProviderEntity, str, str, int]]:
    """Match one string, aggregating per entity.

    Aggregation is required rather than tidy: a single entity can have several
    aliases that overlap on one span -- ``"OpenAI Codex"`` fires both the `codex`
    and the `openai-codex` alias -- and two tags for the same
    `(thread, comment, entity)` violate the uniqueness constraint that keeps a tag
    unambiguous.

    The surviving `matched_text` is the **longest** that fired, because the most
    specific spelling is the most useful thing to show a reviewer asking why a
    thread is tagged. `mentions` takes the **maximum** over the contributing
    aliases rather than their sum, since overlapping aliases would otherwise count
    the same words twice.
    """
    aggregated: dict[int, tuple[HNComment | None, ProviderEntity, str, str, int]] = {}

    for match in find_phrases(text, vocabulary.index):
        entity = vocabulary.by_key.get(match.key)
        if entity is None:
            continue
        existing = aggregated.get(entity.pk)
        if existing is None:
            aggregated[entity.pk] = (
                comment,
                entity,
                match.matched_text,
                match.mode,
                match.mentions,
            )
            continue
        _, known, matched_text, mode, mentions = existing
        longer = len(match.matched_text) > len(matched_text)
        aggregated[entity.pk] = (
            comment,
            known,
            match.matched_text if longer else matched_text,
            match.mode if longer else mode,
            max(mentions, match.mentions),
        )

    return list(aggregated.values())


__all__ = [
    "Candidate",
    "DiscoveredStory",
    "EntityVocabulary",
    "build_comment_tags",
    "build_hn_client",
    "build_title_tags",
    "hn_enabled",
    "keyword_cursor",
    "load_entity_vocabulary",
    "merge_hits",
    "rank_score",
    "refresh_discussions",
    "run_discovery",
    "select_candidates",
    "skip_disabled",
    "sweep_terms",
    "window_slices",
]
