"""Run a Hacker News discussion refresh by hand.

The same code path the hourly Celery task uses -- not a parallel implementation --
so what an operator verifies here is what the schedule will do.

Subclasses `RefreshLeaderboardCommand` for its `_report`, which is source-neutral
by construction: the `SyncRun` counters it prints mean the same thing for a
discussion run as for a leaderboard one. Only the coverage block is overridden,
because "how much of the board matched" is not a question this source has.

`--dry-run` is the flag worth knowing. It performs the full discovery, relevance
filter and tree fetch, writes everything inside one transaction, and rolls that
transaction back -- **including the age-out prune**. The counters it prints are
therefore exactly what a real run would have written, which is how the effect of a
window change is checked before it deletes anything.
"""

from __future__ import annotations

from django.core.management.base import CommandError

from ...services import discussions as discussions_service
from .refresh_leaderboard import Command as RefreshLeaderboardCommand


class Command(RefreshLeaderboardCommand):
    help = "Fetch LLM-related Hacker News threads and persist them."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Do everything, then roll the transaction back -- the prune included. "
                "Prints the counts a real run would have written without changing any "
                "stored data."
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
        parser.add_argument(
            "--hn-id",
            action="append",
            type=int,
            dest="hn_ids",
            metavar="ID",
            help=(
                "Fetch exactly this thread and skip discovery. Repeatable. The way to "
                "debug one story: it reads the item endpoint directly, so no search "
                "result has to mention it."
            ),
        )
        parser.add_argument(
            "--skip-discovery",
            action="store_true",
            help=(
                "Refetch the trees of the threads already stored, without asking the "
                "search API what exists. Leaves the bank's membership unchanged. "
                "Forces the refetch (bypassing the 'has it changed?' gate), which is "
                "how a change to the ProviderAlias table is applied to threads "
                "already stored -- an ordinary hourly run only rebuilds the tags of "
                "threads it refetched."
            ),
        )
        parser.add_argument(
            "--max-trees",
            type=int,
            default=None,
            metavar="N",
            help="Override the per-run tree-fetch budget (default: LEADERBOARD_HN_MAX_TREES_PER_RUN).",
        )
        parser.add_argument(
            "--keep-stale",
            action="store_true",
            help=(
                "Suppress the age-out prune. Debugging only -- with this on, threads "
                "older than the retention window survive, so the bank's size is no "
                "longer bounded."
            ),
        )

    def handle(self, *args, **options) -> None:
        dry_run = options["dry_run"]
        triggered_by = f"cli:{'dry-run' if dry_run else 'manual'}"

        self.stdout.write(
            f"Refreshing Hacker News discussions "
            f"({'dry run -- nothing will be persisted' if dry_run else 'live'})..."
        )

        try:
            run = discussions_service.refresh_discussions(
                triggered_by=triggered_by,
                dry_run=dry_run,
                use_lock=not options["no_lock"],
                hn_ids=options.get("hn_ids"),
                skip_discovery=options["skip_discovery"],
                keep_stale=options["keep_stale"],
                max_trees=options["max_trees"],
            )
        except Exception as exc:  # noqa: BLE001 -- a CLI must exit with a message
            raise CommandError(f"Refresh failed: {type(exc).__name__}: {exc}") from exc

        self._report("hackernews", run)

        if run.status == "failed":
            raise CommandError(
                "The discussion refresh failed. Stored threads were left untouched -- "
                "see the SyncRun row above."
            )

    def _report_coverage(self, run) -> None:
        """What the bank looks like after this run.

        The analogous question to the leaderboard's match rate, and the one a
        silent regression would hide: a run that reports `success` while fetching
        no trees, or while the relevance filter dropped everything, looks perfectly
        healthy in the counters alone.

        Read from the run's own `summary` -- computed in memory before the write --
        never re-derived from the database, because after a dry run's rollback the
        tables describe the *previous* state.
        """
        summary = run.summary or {}
        self.stdout.write("  coverage:")

        if summary.get("stream"):
            self.stdout.write(f"    stream: {summary['stream']}")

        self.stdout.write(
            f"    {summary.get('unique_stories', 0)} unique stories seen from "
            f"{summary.get('window_hits', 0)} window hits and "
            f"{summary.get('keyword_queries', 0)} keyword queries"
        )
        self.stdout.write(
            f"    {summary.get('llm_related', 0)} LLM-related, "
            f"{summary.get('dropped_irrelevant', 0)} dropped as irrelevant"
        )
        self.stdout.write(
            f"    trees: {summary.get('trees_fetched', 0)} fetched, "
            f"{summary.get('trees_unchanged', 0)} unchanged, "
            f"{summary.get('trees_deferred', 0)} deferred, "
            f"{summary.get('trees_failed', 0)} failed, "
            f"{summary.get('trees_skipped_oversize', 0)} oversize"
        )
        self.stdout.write(
            f"    {summary.get('comments_stored', 0)} comments stored this run"
        )
        # The two reasons a thread leaves the bank, reported separately because
        # they mean different things: one is time passing, the other is the
        # floors. A rise in the second is what an operator sees after tightening
        # them, and it is the number `--dry-run` exists to show.
        self.stdout.write(
            f"    {summary.get('threads_pruned', 0)} threads removed "
            f"({summary.get('threads_below_floor', 0)} below the sweep floor, "
            f"the rest aged out)"
        )
        self.stdout.write(
            f"    {summary.get('entities_with_aliases', 0)} entity aliases loaded "
            f"(keyword cursor now {summary.get('keyword_cursor')})"
        )

        if summary.get("window_truncated"):
            self.stdout.write(
                self.style.WARNING(
                    "    the window query was truncated: this run did not see every "
                    "story above the floor, so it must not be read as a ranking"
                )
            )
