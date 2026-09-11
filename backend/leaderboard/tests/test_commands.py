"""The operator-facing surfaces: the CLI and the beat schedule.

Two things are being tested here, and neither is the refresh logic itself (that
is `test_refresh.py`):

* The commands are the *published* interface to the pipeline -- an operator's
  `--dry-run` before a change, and the unmatched report a reviewer works from --
  so their flags, their output and above all their **exit codes** are a contract.
  A refresh command that exits 0 after a failed run would let a cron job believe
  the board was updated.
* The schedule is registered config. A task name with a typo in it, or a
  timezone string `zoneinfo` rejects, fails silently at 08:00 in production and
  nowhere earlier -- so both are asserted here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from leaderboard.constants import Source, SyncStatus, UnmatchedReason
from leaderboard.models import LMArenaEntry, SyncRun, UnmatchedRecord
from leaderboard.services import refresh
from leaderboard.tests.test_api import seed
from leaderboard.tests.test_refresh import (
    aa_client,
    aa_one_model,
    agent_row,
    empty,
    lmarena_client,
    rating_row,
)

SCHEDULE_KEY = "leaderboard-refresh-twice-daily"


# --------------------------------------------------------------------------- #
# `refresh_leaderboard`
# --------------------------------------------------------------------------- #


@pytest.fixture
def wired(monkeypatch):
    """Point the command's client factories at the fakes.

    `build_lmarena_client` / `build_aa_client` are the seam the service already
    uses when no client is injected, so patching them exercises the command's
    *real* path -- flags, dispatch, reporting, exit code -- while keeping the
    network out of it. Stubbing `services.refresh` itself would have tested only
    that the command can forward keyword arguments.
    """
    monkeypatch.setattr(
        refresh,
        "build_lmarena_client",
        lambda **kw: lmarena_client(
            agent=[
                agent_row("Claude Opus 5 (High)", rank=1),
                agent_row("GPT 5.5 (xHigh)", rank=2),
            ],
            document=[rating_row("document", "claude-opus-5-high", rank=4)],
            search=empty("search"),
            webdev=[rating_row("webdev", "claude-opus-5-high", rank=7)],
        ),
    )
    monkeypatch.setattr(refresh, "build_aa_client", lambda **kw: aa_client(aa_one_model()))


@pytest.mark.django_db
class TestRefreshCommand:
    def test_it_runs_the_same_pipeline_as_the_schedule(self, capsys, wired):
        call_command("refresh_leaderboard", "--source=all", "--no-lock")

        out = capsys.readouterr().out
        assert "lmarena: SUCCESS" in out
        assert "artificial_analysis: SUCCESS" in out
        assert LMArenaEntry.objects.filter(category="agent", is_active=True).count() == 2
        assert SyncRun.objects.count() == 2

    def test_it_reports_the_match_rate_not_merely_success(self, capsys, wired):
        """Coverage is the number that matters, and the one a silent regression
        would hide. It is printed on every run rather than left to a separate
        command precisely so an operator sees it without asking."""
        call_command("refresh_leaderboard", "--source=all", "--no-lock")

        out = capsys.readouterr().out
        assert "coverage:" in out
        assert "matched 1/2 agent models to an AA record" in out

    def test_a_dry_run_reports_what_it_would_have_written(self, capsys, wired):
        """The whole point of the flag: real counts, no write. Comparing a
        dry run against the previous run is how a match-rate regression is
        caught before it reaches served data."""
        call_command("refresh_leaderboard", "--source=all", "--dry-run", "--no-lock")

        out = capsys.readouterr().out
        assert "dry run" in out
        assert "seen=4" in out
        assert "coverage:" in out
        assert LMArenaEntry.objects.count() == 0, "a dry run persisted LMArena rows"
        # The run row itself survives, deliberately: it is created outside the
        # data transaction so that a run which produces no data still leaves a
        # record of having been attempted -- and `dry_run=True` on it is what
        # stops it being mistaken for a refresh.
        run = SyncRun.objects.get(source=Source.LMARENA.value)
        assert run.dry_run is True
        assert run.status == SyncStatus.SUCCESS.value

    def test_a_dry_run_does_not_report_a_zero_match_rate(self, capsys, wired):
        """The rollback trap: on `--source=all --dry-run` the agent rows are gone
        by the time AA runs, so they have to be handed over in memory. Without
        that, the command would report a catastrophic 0% match rate against a
        database that is merely empty -- and an operator would believe it."""
        call_command("refresh_leaderboard", "--source=all", "--dry-run", "--no-lock")

        assert "matched 1/2 agent models" in capsys.readouterr().out

    def test_a_source_filter_touches_only_that_source(self, capsys, wired):
        call_command("refresh_leaderboard", "--source=lmarena", "--no-lock")

        out = capsys.readouterr().out
        assert Source.LMARENA.value in out
        assert Source.ARTIFICIAL_ANALYSIS.value not in out
        assert SyncRun.objects.filter(source=Source.ARTIFICIAL_ANALYSIS.value).count() == 0

    def test_a_failed_source_exits_non_zero(self, monkeypatch, wired):
        """The exit code is the contract a cron job or a CI step reads. A command
        that printed the failure and exited 0 would be indistinguishable from
        success to everything that is not a human reading the log."""
        monkeypatch.setattr(
            refresh,
            "build_lmarena_client",
            lambda **kw: lmarena_client(agent=RuntimeError("the Hub is down")),
        )

        with pytest.raises(CommandError, match="One or more sources failed"):
            call_command("refresh_leaderboard", "--source=lmarena", "--no-lock")

        # And the failure is recorded rather than merely printed.
        run = SyncRun.objects.get(source=Source.LMARENA.value)
        assert run.status == SyncStatus.FAILED.value
        assert run.error_code is not None

    def test_a_failed_run_says_the_stored_data_is_untouched(self, monkeypatch, wired, capsys):
        """Reassurance is part of the output contract here: the first question an
        operator asks on a failed refresh is whether the board is now empty."""
        call_command("refresh_leaderboard", "--source=all", "--no-lock")
        good = LMArenaEntry.objects.count()

        monkeypatch.setattr(
            refresh,
            "build_aa_client",
            lambda **kw: aa_client(aa_page_with_no_models()),
        )
        with pytest.raises(CommandError) as excinfo:
            call_command("refresh_leaderboard", "--source=artificial_analysis", "--no-lock")

        # `call_command` re-raises rather than printing, so the reassurance
        # travels on the exception -- which is what a shell sees, too.
        assert "Stored data was left untouched" in str(excinfo.value)
        assert LMArenaEntry.objects.count() == good

    def test_a_held_lock_skips_rather_than_queueing(self, capsys, wired):
        """A scheduled run that finds last night's run still going must stand
        down -- not stack up behind it and then fire twice in a row."""
        from leaderboard.locking import run_lock

        with run_lock(refresh.ALL_SOURCES_LOCK):
            call_command("refresh_leaderboard", "--source=all")

        out = capsys.readouterr().out
        assert "SKIPPED" in out
        assert LMArenaEntry.objects.count() == 0

    def test_an_unknown_source_is_rejected_by_the_parser(self):
        """argparse's own error path: a typo'd source must not silently become
        the default. Django wraps it in `CommandError`, which exits 1."""
        with pytest.raises(CommandError, match="invalid choice"):
            call_command("refresh_leaderboard", "--source=nope")


def aa_page_with_no_models():
    """An empty AA catalogue -- rejected by the client before parsing."""
    from leaderboard.tests.fakes import aa_page

    return aa_page([])


# --------------------------------------------------------------------------- #
# `report_unmatched`
# --------------------------------------------------------------------------- #


def record(
    *,
    source: str = Source.ARTIFICIAL_ANALYSIS.value,
    category: str = "",
    reason: str = UnmatchedReason.NO_LMARENA_MATCH.value,
    model_key: str = "some-model-high",
    model_name: str = "Some Model (High)",
    is_current: bool = True,
    detail: dict | None = None,
) -> UnmatchedRecord:
    now = datetime.now(tz=timezone.utc)
    return UnmatchedRecord.objects.create(
        source=source,
        category=category,
        reason=reason,
        model_key=model_key,
        model_name=model_name,
        occurrences=3,
        is_current=is_current,
        first_seen_at=now,
        last_seen_at=now,
        detail=detail or {},
    )


@pytest.mark.django_db
class TestReportUnmatched:
    def test_nothing_unmatched_is_stated_rather_than_shown_as_an_empty_table(self, capsys):
        """An empty table is ambiguous -- it reads like a rendering failure. The
        sentence says the thing an operator wants to know."""
        call_command("report_unmatched")

        assert "Nothing unmatched. Every record joined." in capsys.readouterr().out

    def test_the_table_names_the_exact_strings_an_alias_needs(self, capsys):
        """The output is designed to be pasted into a `ModelAlias`: `raw_name` is
        the verbatim upstream spelling and `canonical_key` is the key it failed to
        resolve to. Both must therefore be in the report."""
        record(model_name="Some Model (High)", model_key="some-model-high")

        call_command("report_unmatched")

        out = capsys.readouterr().out
        assert "Some Model (High)" in out
        assert "some-model-high" in out
        assert "By reason:" in out
        assert "no_lmarena_match" in out
        # The reason help is what turns a code into an action.
        assert "needs an alias" in out

    def test_markdown_output_is_a_pasteable_table(self, capsys):
        record(detail={"candidates": ["a", "b"]})

        call_command("report_unmatched", "--format=md")

        lines = capsys.readouterr().out.splitlines()
        table = [line for line in lines if line.startswith("|")]
        assert table[0].startswith("| Source | Category | Reason |")
        assert set(table[1]) <= set("| -")
        assert len(table) == 3, f"expected a header, a separator and one row: {table}"

    def test_an_empty_category_renders_as_a_dash_not_as_none(self, capsys):
        """`None` on a page is the string "None" to a reader."""
        record(category="")

        call_command("report_unmatched", "--format=md")

        assert "| — |" in capsys.readouterr().out

    def test_a_pipe_in_the_detail_does_not_break_the_table(self, capsys):
        record(detail={"note": "a|b"})

        call_command("report_unmatched", "--format=md")

        row = [line for line in capsys.readouterr().out.splitlines() if line.startswith("| a") or "a\\|b" in line]
        assert row, "the escaped detail is missing"

    def test_json_output_is_machine_readable(self, capsys):
        import json

        record(detail={"reason_detail": 1})

        call_command("report_unmatched", "--format=json")

        payload = json.loads(capsys.readouterr().out.split("\nBy reason:")[0])
        assert isinstance(payload, list)
        assert payload[0]["model_key"] == "some-model-high"
        assert payload[0]["detail"] == {"reason_detail": 1}

    def test_the_filters_are_applied_together(self, capsys):
        record(model_key="aa-orphan", source=Source.ARTIFICIAL_ANALYSIS.value)
        record(
            model_key="search-only",
            source=Source.LMARENA.value,
            category="search",
            reason=UnmatchedReason.NOT_IN_AGENT_SET.value,
        )

        call_command("report_unmatched", "--format=json", "--category=search")

        import json

        payload = json.loads(capsys.readouterr().out.split("\nBy reason:")[0])
        assert [row["model_key"] for row in payload] == ["search-only"]

    def test_search_matches_the_key_as_well_as_the_name(self, capsys):
        """The key is often the only thing an operator has -- it is what the
        unmatched report and the URL use."""
        import json

        record(model_key="gpt-5-5-xhigh", model_name="GPT 5.5 (xHigh)")

        call_command("report_unmatched", "--format=json", "--search=xhigh")

        payload = json.loads(capsys.readouterr().out.split("\nBy reason:")[0])
        assert len(payload) == 1

    def test_a_stale_record_is_hidden_by_default_and_shown_on_request(self, capsys):
        """`is_current=False` means the record stopped appearing upstream. It is
        kept -- deleting it would erase the history of a fixed problem -- but it
        must not pad the default report."""
        import json

        record(model_key="fixed-long-ago", is_current=False)

        call_command("report_unmatched", "--format=json")
        assert json.loads(capsys.readouterr().out.split("\nBy reason:")[0]) == []

        call_command("report_unmatched", "--format=json", "--all")
        payload = json.loads(capsys.readouterr().out.split("\nBy reason:")[0])
        assert [row["model_key"] for row in payload] == ["fixed-long-ago"]

    def test_a_limit_says_what_it_hid(self, capsys):
        for index in range(5):
            record(model_key=f"model-{index}")

        call_command("report_unmatched", "--limit=2")

        assert "(showing 2 of 5 rows)" in capsys.readouterr().out

    def test_the_real_pipeline_output_is_reviewable(self, capsys):
        """Against data the ingestion pipeline actually wrote, not hand-built
        rows -- the reason codes and the detail payload have to line up."""
        seed()

        call_command("report_unmatched", "--format=md")

        out = capsys.readouterr().out
        assert "unrelated-model" in out
        assert UnmatchedReason.NO_LMARENA_MATCH.value in out


# --------------------------------------------------------------------------- #
# The beat schedule
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestBeatSchedule:
    def test_the_configured_timezone_is_a_real_iana_zone(self):
        """The P0 regression guard.

        The scaffold shipped `CELERY_TIMEZONE = "China/Shanghai"`, which is not
        an IANA zone. `ZoneInfo` raises `ZoneInfoNotFoundError`, and celery-beat
        refuses to start at all -- so the failure mode is not a schedule at the
        wrong hour, it is *no schedule*, discovered when the board goes stale.
        """
        try:
            zone = ZoneInfo(settings.CELERY_TIMEZONE)
        except ZoneInfoNotFoundError as exc:  # pragma: no cover - the failure case
            raise AssertionError(
                f"CELERY_TIMEZONE={settings.CELERY_TIMEZONE!r} is not a valid IANA "
                f"zone; celery-beat cannot start: {exc}"
            ) from exc

        assert zone is not None

    def test_the_crontab_fires_twice_a_day(self):
        schedule = settings.CELERY_BEAT_SCHEDULE[SCHEDULE_KEY]["schedule"]

        # Celery expands the cronspec at construction, so these are sets of
        # integers rather than the strings in `CELERY_BEAT_SCHEDULE`.
        assert sorted(schedule.hour) == [8, 20]
        assert sorted(schedule.minute) == [0]
        # Every day of the week and month: a plain twice-daily timer, not a
        # weekday-only variant. Celery expands the cronspec at construction, so
        # a "*" arrives here as the full set rather than as a string.
        assert len(schedule.day_of_month) == 31
        assert len(schedule.month_of_year) == 12
        assert len(schedule.day_of_week) == 7

    def test_the_two_local_times_are_noon_and_midnight_utc(self):
        """The schedule is written in Asia/Shanghai (UTC+8, no DST) because that
        is the timezone the operators think in; the API and the database are UTC.
        Both runs land on convenient UTC boundaries, which is a coincidence worth
        keeping visible -- if the zone ever changes, this test says so."""
        zone = ZoneInfo(settings.CELERY_TIMEZONE)

        converted = [
            datetime(2026, 9, 11, hour, 0, tzinfo=zone).astimezone(timezone.utc)
            for hour in sorted(settings.CELERY_BEAT_SCHEDULE[SCHEDULE_KEY]["schedule"].hour)
        ]

        assert [(moment.hour, moment.minute) for moment in converted] == [(0, 0), (12, 0)]

    def test_only_the_orchestrator_is_scheduled(self):
        """One entry, one task. LMArena and AA are refreshed inside `refresh_all`
        in-process, because AA's retention and matching both read the agent set
        LMArena just wrote -- scheduling them independently would let AA match
        against a stale agent set on a cold database."""
        assert list(settings.CELERY_BEAT_SCHEDULE) == [SCHEDULE_KEY]
        assert settings.CELERY_BEAT_SCHEDULE[SCHEDULE_KEY]["task"] == "leaderboard.refresh_all"

    def test_a_late_run_expires_rather_than_firing_stale(self):
        """If beat was down for a day, the missed run is worse than useless: it
        would write day-old data and the next run is hours away."""
        assert settings.CELERY_BEAT_SCHEDULE[SCHEDULE_KEY]["options"]["expires"] == 3600

    def test_the_database_scheduler_is_the_one_configured(self):
        """So an operator can pause a run from the admin without a deploy."""
        assert settings.CELERY_BEAT_SCHEDULER == "django_celery_beat.schedulers:DatabaseScheduler"

    def test_every_scheduled_task_name_actually_exists(self):
        """A typo'd task name is invisible until 08:00, and then it fails inside
        a worker log nobody is reading. Resolving the name here turns it into a
        red test instead."""
        import leaderboard.tasks  # noqa: F401 -- registers the tasks
        from llm_picker_backend.celery import app

        registered = set(app.tasks)
        for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
            assert entry["task"] in registered, (
                f"{name!r} schedules {entry['task']!r}, which is not a registered task"
            )

    def test_the_tasks_are_reachable_by_their_published_names(self):
        """The names in the schedule are part of the operator interface: they are
        what `celery -A ... call leaderboard.refresh_all` takes."""
        from leaderboard import tasks

        assert tasks.refresh_all.name == "leaderboard.refresh_all"
        assert tasks.refresh_lmarena.name == "leaderboard.refresh_lmarena"
        assert tasks.refresh_aa.name == "leaderboard.refresh_aa"


@pytest.mark.django_db
class TestTaskEntryPoints:
    """The tasks are thin, but "thin" is not "nothing to get wrong": each one
    resolves its own arguments and returns a serializable summary."""

    def test_refresh_all_returns_a_json_serializable_summary(self, monkeypatch):
        import json

        from leaderboard import tasks

        monkeypatch.setattr(
            refresh,
            "build_lmarena_client",
            lambda **kw: lmarena_client(
                agent=[agent_row("Claude Opus 5 (High)")],
                document=empty("document"),
                search=empty("search"),
                webdev=empty("webdev"),
            ),
        )
        monkeypatch.setattr(refresh, "build_aa_client", lambda **kw: aa_client(aa_one_model()))

        result = tasks.refresh_all.apply(kwargs={"dry_run": True}).get()

        assert json.loads(json.dumps(result)) == result
        assert set(result) == {Source.LMARENA.value, Source.ARTIFICIAL_ANALYSIS.value}
        assert result[Source.LMARENA.value]["status"] == SyncStatus.SUCCESS.value

    def test_a_task_records_who_triggered_it(self, monkeypatch):
        """`triggered_by` distinguishes a scheduled run from a human one, which
        is the first question asked about an unexpected refresh."""
        from leaderboard import tasks

        monkeypatch.setattr(
            refresh,
            "build_lmarena_client",
            lambda **kw: lmarena_client(
                agent=[agent_row("Claude Opus 5 (High)")],
                document=empty("document"),
                search=empty("search"),
                webdev=empty("webdev"),
            ),
        )

        tasks.refresh_lmarena.apply(kwargs={"dry_run": True}).get()
        run = SyncRun.objects.get(source=Source.LMARENA.value)

        assert run.triggered_by == "celery:manual"
