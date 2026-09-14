"""Fetch fresh data at launch -- but only when what is stored has actually aged out.

`refresh_leaderboard` answers "fetch now". This answers the other question the
dev environment keeps asking: "is the board I am about to serve out of date?"
The twice-daily Celery schedule is the normal answer to that, but it presumes
beat and a worker are always running. On a laptop they usually are not, so a
developer starts `runserver` against data that is days old, `/metadata/` reports
`is_stale: true`, and nothing corrects it until someone remembers.

Wire it in ahead of the server in a start script:

```bash
uv run python manage.py refresh_if_stale || true
uv run python manage.py runserver
```

**A failed refresh does not stop a launch**, which is why that `|| true` is
belt-and-braces rather than load-bearing: the whole design of the read path is
that a source being down costs freshness, never availability, and the API serves
the last good data with `is_stale: true` while it waits. `--strict` is the
opt-in for a script that would rather refuse to start than serve old data.

Two gates, and both must open:

* **Staleness.** Measured off `last_success_at` -- the age of the *served* data,
  not of the last attempt -- against `constants.stale_after_seconds()`. That
  threshold helper is shared with `/metadata/`, which is what stops the command
  and the API disagreeing about the number; the *query* is not shared, because
  `api/selectors.py` must stay the leaf of the dependency graph and may not be
  imported from here. `test_the_stale_threshold_is_the_one_the_api_reports` is
  what holds the two together, so it is not a test to delete.
* **Cooldown.** The last attempt, whatever its outcome, blocks another for
  `LEADERBOARD_STARTUP_REFRESH_COOLDOWN_SECONDS`. Without it, a failing refresh
  would re-attempt on every boot of a crash-looping or file-watching process, and
  each Artificial Analysis attempt can spend up to 4 of the 100 requests shared
  across the entire organization per day. `--force` bypasses both gates.

A skip counts as an attempt for the cooldown, which is deliberate: a refresh that
could not start because another run held the lock becomes a 30-minute reprieve
rather than a retry on the next boot.

`refresh_all` is always called, even when only one source is stale. That is not
an oversight -- Artificial Analysis retention and matching both read the LMArena
agent set, so on a database with no agent rows an AA-only run would retain
nothing. The cost is re-downloading the LMArena dataset when only AA has aged,
which is bandwidth rather than quota; the 100 shared AA requests are protected by
the cooldown and by the quota preflight.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connection

from ... import persistence as store
from ...constants import Source, SyncStatus, stale_after_seconds
from ...models import SyncRun
from ...services import refresh as refresh_service
from .refresh_leaderboard import Command as RefreshLeaderboardCommand

SOURCES: tuple[str, ...] = (Source.LMARENA.value, Source.ARTIFICIAL_ANALYSIS.value)

#: `refresh_all` returns the two sources keyed by their `Source` value.
FAILED = "failed"


def _aware(value: datetime | None) -> datetime | None:
    """Timestamps come back aware under `USE_TZ`, but never assume it."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _format_age(seconds: int | None) -> str:
    if seconds is None:
        return "never"
    hours, minutes = divmod(seconds // 60, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


@dataclass(frozen=True)
class SourceState:
    """What one source looks like right now, and what that implies."""

    source: str
    last_success_at: datetime | None
    age_seconds: int | None
    is_stale: bool


class Command(RefreshLeaderboardCommand):
    """Subclasses the manual command purely to reuse its reporting.

    `_report` and `_report_coverage` are the reviewed description of what a run
    did -- counters, failed categories, AA quota, match coverage. Re-implementing
    a thinner version here would mean two accounts of the same run drifting
    apart, so the inheritance is deliberate and narrow: `add_arguments` and
    `handle` are both replaced outright.
    """

    help = (
        "Refresh both sources at launch, but only when the stored data is stale. "
        "Intended for a start script; never blocks a launch on a failed refresh."
    )

    def add_arguments(self, parser) -> None:
        """No `--source`: the stale check decides scope, and it decides `all`.

        LMArena must be refreshed before Artificial Analysis -- AA's retention
        flag and its match against the agent set both read agent entries, so on a
        cold database an AA run that went first would retain nothing. Letting a
        caller pick one source here would expose exactly that footgun, and
        `refresh_leaderboard --source=` already exists for the deliberate case.
        """
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Refresh even if the data is fresh, and ignore the cooldown. The "
                "explicit 'I know it is up to date, fetch anyway'."
            ),
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help=(
                "Report the freshness of each source and exit without refreshing. "
                "Always exits 0 -- it is a report, not a gate."
            ),
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help=(
                "Exit non-zero if a refresh was attempted and a source failed. "
                "Without it a failed refresh still exits 0, because the API is "
                "designed to keep serving the last good data."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Do everything, then roll the transaction back. Note this still "
                "consumes Artificial Analysis quota."
            ),
        )
        parser.add_argument(
            "--no-lock",
            action="store_true",
            help="Skip the Redis overlap lock.",
        )

    # -- freshness ---------------------------------------------------------- #

    def _database_is_migrated(self) -> bool:
        """A start script may run this before `migrate`; that must not be fatal."""
        return SyncRun._meta.db_table in connection.introspection.table_names()

    def _states(self, *, now: datetime, threshold: int) -> list[SourceState]:
        states = []
        for source in SOURCES:
            succeeded = _aware(store.last_success_at(source))
            age = int((now - succeeded).total_seconds()) if succeeded else None
            states.append(
                SourceState(
                    source=source,
                    last_success_at=succeeded,
                    age_seconds=age,
                    # Identical to `source_freshness`: never refreshed and too old
                    # are one state, because the served data is equally untrustworthy.
                    is_stale=age is None or age > threshold,
                )
            )
        return states

    def _cooldown_elapsed(self, *, now: datetime) -> int | None:
        """Seconds since the last real attempt, across both sources.

        Dry runs are excluded: a rehearsal writes no data, so letting one reset
        the cooldown would silence the guard without changing what is stored.
        """
        started = _aware(
            SyncRun.objects.filter(dry_run=False)
            .order_by("-started_at")
            .values_list("started_at", flat=True)
            .first()
        )
        return int((now - started).total_seconds()) if started else None

    # -- reporting ---------------------------------------------------------- #

    def _report_states(self, states, *, threshold: int) -> None:
        self.stdout.write(f"Staleness threshold: {_format_age(threshold)}")
        for state in states:
            if state.last_success_at is None:
                detail = "never refreshed"
            else:
                detail = (
                    f"last success {state.last_success_at:%Y-%m-%d %H:%M} UTC, "
                    f"age {_format_age(state.age_seconds)}"
                )
            verdict = self.style.WARNING("STALE") if state.is_stale else "fresh"
            self.stdout.write(f"  {state.source}: {detail} -> {verdict}")

    # -- entry point -------------------------------------------------------- #

    def handle(self, *args, **options) -> None:
        if not self._database_is_migrated():
            self.stdout.write(
                self.style.WARNING(
                    "The leaderboard tables do not exist yet, so freshness is "
                    "unknown; skipping the refresh. Run `manage.py migrate` first."
                )
            )
            self._verdict("skipped (not migrated)")
            return

        now = store.utcnow()
        threshold = stale_after_seconds()
        states = self._states(now=now, threshold=threshold)
        self._report_states(states, threshold=threshold)

        if options["check"]:
            self.stdout.write("")
            self.stdout.write("--check: nothing was refreshed.")
            self._verdict("checked")
            return

        force = options["force"]
        stale = [state for state in states if state.is_stale]

        if not stale and not force:
            self.stdout.write(self.style.SUCCESS("Data is fresh; no refresh needed."))
            self._verdict("fresh")
            return

        cooldown = max(
            0, int(getattr(settings, "LEADERBOARD_STARTUP_REFRESH_COOLDOWN_SECONDS", 0))
        )
        elapsed = self._cooldown_elapsed(now=now)

        if not force and cooldown and elapsed is not None and elapsed < cooldown:
            self.stdout.write(
                self.style.WARNING(
                    f"Data is stale, but a refresh was attempted {_format_age(elapsed)} "
                    f"ago and the cooldown is {_format_age(cooldown)}; skipping. "
                    "Use --force to refresh anyway."
                )
            )
            self._verdict("skipped (cooldown)")
            return

        reason = "requested with --force" if not stale else "data is stale"
        self.stdout.write("")
        self.stdout.write(f"Refreshing both sources ({reason})...")

        try:
            runs = refresh_service.refresh_all(
                triggered_by="cli:startup",
                dry_run=options["dry_run"],
                use_lock=not options["no_lock"],
            )
        except Exception as exc:  # noqa: BLE001 -- a launch must not die here
            # `refresh_lmarena` and `refresh_aa` promise never to raise, but that
            # promise begins *inside* their own per-source `try`: the stale-run
            # reaper and the run claim execute before it, so a locked or corrupt
            # database still arrives here. `refresh_leaderboard` already converts
            # this into a message for the same reason -- the difference is that
            # this command must not turn it into a non-zero exit.
            self._report_crash(exc, strict=options["strict"])
            return

        for name, run in runs.items():
            self._report(name, run)

        failed = [name for name, run in runs.items() if run.status == FAILED]
        skipped = [name for name, run in runs.items() if run.status == SyncStatus.SKIPPED.value]

        if not failed:
            # A skip is not a success, and saying "refreshed" over an all-skipped
            # run would be exactly the kind of quiet overstatement the freshness
            # block exists to prevent.
            self._verdict("skipped" if len(skipped) == len(runs) else "refreshed")
            return

        message = (
            f"{', '.join(sorted(failed))} failed. Stored data was left untouched -- "
            "the API keeps serving the last good data with `is_stale: true`. See "
            "`manage.py refresh_leaderboard` for a full report."
        )
        if options["strict"]:
            raise CommandError(message)
        self.stdout.write(self.style.WARNING(message))
        self._verdict("failed")

    def _verdict(self, outcome: str) -> None:
        """One greppable line, whatever happened.

        A start script's log is read by `grep`, not by a human scrolling: without
        this, "the run was skipped" and "the run never happened" look the same.
        """
        self.stdout.write(f"startup refresh: {outcome}")

    def _report_crash(self, exc: Exception, *, strict: bool) -> None:
        message = f"Refresh failed before it could run: {type(exc).__name__}: {exc}"
        if strict:
            raise CommandError(message) from exc
        self.stdout.write(self.style.ERROR(message))
        self.stdout.write(
            self.style.WARNING(
                "The API keeps serving the last good data and reports `is_stale: true`."
            )
        )
        self._verdict("failed")
