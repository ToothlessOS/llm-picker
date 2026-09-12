"""Celery entry points.

Deliberately thin. Every task here does three things and nothing else: resolve
its arguments, call one `services.refresh` function, and return a small JSON
summary. All the orchestration lives in the service layer so it is testable
without a broker -- which matters, because the interesting behaviour here is
"what happens when the upstream is broken", and that is far easier to assert
with a direct call than with a worker in the loop.

The service functions never raise; they return a `SyncRun` whose `status` says
what happened. That is why these tasks are not decorated with `autoretry_for`:
a failed refresh is an expected, recorded outcome, not a transient task error
worth retrying into the shared quota.
"""

from __future__ import annotations

import logging

from celery import shared_task

from .models import SyncRun
from .services import refresh as refresh_service

logger = logging.getLogger(__name__)


def _summary(run: SyncRun) -> dict:
    return {
        "id": run.id,
        "source": run.source,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "records_seen": run.records_seen,
        "records_created": run.records_created,
        "records_updated": run.records_updated,
        "records_deactivated": run.records_deactivated,
        "records_failed": run.records_failed,
        "records_deduplicated": run.records_deduplicated,
        "anomalies_recorded": run.anomalies_recorded,
        "error_code": run.error_code,
        "error_message": run.error_message,
    }


@shared_task(bind=True, name="leaderboard.refresh_all")
def refresh_all(self, dry_run: bool = False) -> dict:
    """The twice-daily refresh. **This is the only task the schedule runs.**

    Both sources are refreshed inside this one task, in-process and in order,
    rather than fanned out with `.delay()`. Artificial Analysis retention and
    matching both read the LMArena `agent` set, so on a cold database an
    independently-scheduled AA task can run first, find no agent entries, and
    correctly-but-uselessly retain nothing.
    """
    runs = refresh_service.refresh_all(
        triggered_by="celery:beat",
        dry_run=dry_run,
        celery_task_id=self.request.id or "",
    )
    return {source: _summary(run) for source, run in runs.items()}


@shared_task(bind=True, name="leaderboard.refresh_lmarena")
def refresh_lmarena(self, dry_run: bool = False) -> dict:
    """Ops/manual: refresh only the LMArena categories."""
    run = refresh_service.refresh_lmarena(
        triggered_by="celery:manual",
        dry_run=dry_run,
        celery_task_id=self.request.id or "",
    )
    return _summary(run)


@shared_task(bind=True, name="leaderboard.refresh_aa")
def refresh_aa(self, dry_run: bool = False) -> dict:
    """Ops/manual: refresh only the Artificial Analysis catalogue.

    Note this rebuilds the AA <-> agent matches from whatever agent entries are
    currently stored. If the LMArena side has never been refreshed, nothing
    will match -- run `leaderboard.refresh_all` instead.
    """
    run = refresh_service.refresh_aa(
        triggered_by="celery:manual",
        dry_run=dry_run,
        celery_task_id=self.request.id or "",
    )
    return _summary(run)
