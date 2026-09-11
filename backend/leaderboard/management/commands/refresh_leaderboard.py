"""Run a leaderboard refresh by hand.

The same code path the twice-daily Celery task uses -- not a parallel
implementation -- so what an operator verifies here is what the schedule will
do.

`--dry-run` is the interesting flag. It performs the full fetch, parse, dedupe
and match, writes everything inside one transaction, and then rolls that
transaction back. The reported counters are therefore *exactly* what a real run
would have written, including how many models would have been deactivated and
how many records failed to match -- which is how a match-rate regression is
caught before it reaches the served data.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from ...constants import Source
from ...services import refresh as refresh_service

SOURCE_CHOICES = ("all", Source.LMARENA.value, Source.ARTIFICIAL_ANALYSIS.value)


class Command(BaseCommand):
    help = "Fetch leaderboard data from the external sources and persist it."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            choices=SOURCE_CHOICES,
            default="all",
            help=(
                "Which source to refresh. 'all' (the default) runs LMArena first, "
                "then Artificial Analysis, because AA retention and matching both "
                "depend on the agent entries LMArena just wrote."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Do everything, then roll the transaction back. Prints the counts a "
                "real run would have written without changing any stored data."
            ),
        )
        parser.add_argument(
            "--no-lock",
            action="store_true",
            help=(
                "Skip the Redis overlap lock. Useful on a machine without Redis; the "
                "database constraint on SyncRun still prevents a genuine overlap."
            ),
        )

    def handle(self, *args, **options) -> None:
        source = options["source"]
        dry_run = options["dry_run"]
        use_lock = not options["no_lock"]
        triggered_by = f"cli:{'dry-run' if dry_run else 'manual'}"

        self.stdout.write(
            f"Refreshing {source} "
            f"({'dry run -- nothing will be persisted' if dry_run else 'live'})..."
        )

        try:
            runs = self._dispatch(
                source,
                triggered_by=triggered_by,
                dry_run=dry_run,
                use_lock=use_lock,
            )
        except CommandError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a CLI must exit with a message
            raise CommandError(f"Refresh failed: {type(exc).__name__}: {exc}") from exc

        for name, run in runs.items():
            self._report(name, run)

        if any(run.status == "failed" for run in runs.values()):
            raise CommandError(
                "One or more sources failed. Stored data was left untouched -- see "
                "`manage.py report_unmatched` and the SyncRun rows above."
            )

    def _dispatch(self, source, *, triggered_by, dry_run, use_lock):
        if source == "all":
            return refresh_service.refresh_all(
                triggered_by=triggered_by, dry_run=dry_run, use_lock=use_lock
            )
        if source == Source.LMARENA.value:
            return {
                source: refresh_service.refresh_lmarena(
                    triggered_by=triggered_by, dry_run=dry_run, use_lock=use_lock
                )
            }
        return {
            source: refresh_service.refresh_aa(
                triggered_by=triggered_by, dry_run=dry_run, use_lock=use_lock
            )
        }

    def _report(self, name: str, run) -> None:
        style = self.style.SUCCESS if run.status in ("success", "partial") else self.style.WARNING
        self.stdout.write("")
        self.stdout.write(style(f"{name}: {run.status.upper()}  (run #{run.id})"))
        self.stdout.write(
            f"  seen={run.records_seen} created={run.records_created} "
            f"updated={run.records_updated} unchanged={run.records_unchanged}"
        )
        self.stdout.write(
            f"  deactivated={run.records_deactivated} failed={run.records_failed} "
            f"deduplicated={run.records_deduplicated} anomalies={run.anomalies_recorded}"
        )
        self.stdout.write(f"  duration={run.duration_ms}ms")

        if run.fields_succeeded:
            self.stdout.write(f"  fields succeeded: {', '.join(run.fields_succeeded)}")
        if run.fields_failed:
            for field, error in run.fields_failed.items():
                self.stdout.write(self.style.ERROR(f"  field failed: {field}: {error}"))

        if run.rate_limit_limit is not None:
            self.stdout.write(
                f"  AA quota: {run.rate_limit_remaining}/{run.rate_limit_limit} remaining "
                f"(tier={run.tier or 'unknown'}, reset={run.rate_limit_reset_at})"
            )
        if run.error_code:
            self.stdout.write(self.style.ERROR(f"  error: {run.error_code}: {run.error_message}"))

        self._report_coverage(run)

    def _report_coverage(self, run) -> None:
        """What the board looks like after this run -- the number that matters.

        A refresh that reports `success` with a silently collapsed match rate is
        the failure this project most needs to make visible, so coverage is
        printed on every run rather than left to a separate command.

        Read from the run's own `summary` (computed in memory before the write),
        never re-derived from the database: after a dry run's rollback the tables
        describe the *previous* state, so a database query here would confidently
        report a coverage figure that belongs to a different run.
        """
        summary = run.summary or {}
        self.stdout.write("  coverage:")

        if run.source == Source.LMARENA.value:
            entries = summary.get("entries") or {}
            in_set = summary.get("in_agent_set") or {}
            if not entries:
                self.stdout.write("    no categories loaded")
                return
            for category, total in entries.items():
                self.stdout.write(
                    f"    {category}: {total} models, {in_set.get(category, 0)} in the agent set"
                )
            return

        agent_models = summary.get("agent_models")
        matched = summary.get("matched")
        if not agent_models:
            self.stdout.write("    no LMArena agent entries to match against")
            return
        self.stdout.write(
            f"    matched {matched}/{agent_models} agent models to an AA record "
            f"({summary.get('coverage_percent')}%)"
        )
        self.stdout.write(
            f"    {summary.get('aa_records')} AA records: "
            f"{summary.get('unmatched')} unmatched, "
            f"{summary.get('duplicates')} duplicate claims"
        )
        if not summary.get("matches_persisted", True):
            self.stdout.write(
                "    (agent set was supplied in memory -- match rows were not written)"
            )
