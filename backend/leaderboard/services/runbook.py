"""Run bookkeeping shared by every ingestion service.

`refresh.py` and `discussions.py` write the same three things around their real
work -- a "we chose not to run" row, the `running` row that claims a source, and
the per-run counters -- and none of it is source-specific. It lives here rather
than in either service so the two cannot drift: a `skipped` row that meant
something subtly different for Hacker News would make `/metadata/`'s
`recent_runs` unreadable across sources.

The overlap protection is two layers, and this module owns the second:

1. `locking.run_lock` -- Redis, fail-open to "acquired", means *skip* never queue.
2. The conditional unique index on `SyncRun` (`source` where `status='running'`),
   which holds even when the cache is unreachable. `claim_run` is where that
   layer is actually met, and it is why the `IntegrityError` is caught here: it
   is an expected outcome, not a bug.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from .. import persistence as store
from ..constants import SyncStatus
from ..models import SyncRun
from ..persistence import UpsertStats

#: A `running` row older than this is assumed to belong to a dead worker.
STALE_RUNNING_SECONDS = 6 * 3600


def counters(stats: UpsertStats) -> dict[str, int]:
    """Per-run counters, named as the `SyncRun` columns are.

    The columns are source-neutral on purpose, which is what lets one `_summary`
    in `tasks.py` describe a leaderboard refresh and a discussion refresh alike.
    """
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


def skipped(
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


def claim_run(
    source: str,
    *,
    triggered_by: str,
    dry_run: bool,
    celery_task_id: str,
) -> SyncRun | None:
    """Open a `running` row, or ``None`` when one is already open for this source.

    ``None`` means the conditional unique index fired -- the database-level
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


__all__ = ["STALE_RUNNING_SECONDS", "claim_run", "counters", "skipped"]
