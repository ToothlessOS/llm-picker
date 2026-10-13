"""Ingestion, idempotency and the "don't destroy the last good data" rules.

This module is where the five safety rules in the design are actually enforced
rather than described:

1. no `DELETE` against a data table -- deactivation is `is_active=False`;
2. every write for one source happens in one `transaction.atomic()`;
3. a failed run leaves the previous rows byte-identical;
4. `deactivate_missing` runs only after a complete, non-empty fetch;
5. a 200 with zero models fails the run instead of emptying the table.

Each has a test below named for the rule it guards, because the cost of a
regression here is a blank leaderboard rather than a wrong number.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from leaderboard.clients.artificial_analysis import ArtificialAnalysisClient
from leaderboard.clients.http import RetryPolicy
from leaderboard.clients.lmarena import LMArenaClient, LoadedSplit
from leaderboard.constants import MatchMethod, Source, SyncStatus, UnmatchedReason
from leaderboard.models import LLMModel, LMArenaEntry, ModelMatch, SyncRun, UnmatchedRecord
from leaderboard.services import refresh
from leaderboard.tests.fakes import (
    FakeLoader,
    FakeTransport,
    SleepRecorder,
    aa_model,
    aa_page,
    loaded,
    upper_bound_uniform,
)
from leaderboard.validation import required_columns

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def agent_row(name: str, rank: int = 1, **overrides) -> dict:
    row = {
        "model_name": name,
        "organization": "anthropic",
        "license": "Proprietary",
        "rank": rank,
        "category": "overall",
        "leaderboard_publish_date": "2026-09-08",
        "score": 0.114,
        "score_ci_lower": 0.096,
        "score_ci_upper": 0.131,
        "observation_count": 2_794_373,
        "session_count": 23_232,
    }
    row.update(overrides)
    return row


def rating_row(category: str, name: str, rank: int = 1, **overrides) -> dict:
    row = {
        "model_name": name,
        "organization": "anthropic",
        "license": "Proprietary",
        "rank": rank,
        "category": "overall",
        "leaderboard_publish_date": "2026-07-30",
        "rating": 1520.1,
        "rating_lower": 1505.4,
        "rating_upper": 1534.7,
        "variance": 55.6,
        "vote_count": 1663,
    }
    row.update(overrides)
    return row


def lmarena_client(**splits) -> LMArenaClient:
    """A client whose four categories are whatever the caller names.

    Three value kinds are accepted:

    * a list of row dicts -- wrapped into a `LoadedSplit` whose columns are
      derived from the rows;
    * a `LoadedSplit` -- used as given, which is how a *legitimately empty* split
      is expressed (deriving columns from zero rows would produce an empty
      column list and fail schema validation instead);
    * an `Exception` -- raised by the loader, which is how "this field failed"
      is set up.

    A category that is simply *absent* also fails, loudly: the loader asserts
    rather than returning nothing, so a test that forgets a category gets a
    failure instead of a silently-empty split. Use `empty(category)` when an
    empty split is what the test actually means.
    """
    prepared = {}
    for category, value in splits.items():
        if isinstance(value, Exception) or isinstance(value, LoadedSplit):
            prepared[category] = value
        else:
            prepared[category] = loaded(value)
    return LMArenaClient(loader=FakeLoader(prepared), sleep=SleepRecorder())


def empty(category: str) -> LoadedSplit:
    """A split that loaded successfully and holds no rows.

    Distinct from a *failed* load, and the distinction is the whole point of
    rule 4: an empty split is evidence the category is empty; a failed load is
    evidence of nothing at all.
    """
    return loaded([], columns=required_columns(category))


def with_categories(**splits) -> LMArenaClient:
    """A client where every category the caller does not name loaded successfully
    and is simply empty.

    This is the right default for a test about *one* category: without it, the
    categories the test does not care about fail to load, and every such run
    comes back `partial`. That would quietly weaken assertions like
    `records_created == 0`, which then mean "zero rows in the one category that
    loaded" rather than "zero rows".
    """
    full = {category: empty(category) for category in ("agent", "document", "search", "webdev")}
    full.update(splits)
    return lmarena_client(**full)


def aa_client(*pages, **kwargs) -> ArtificialAnalysisClient:
    transport = FakeTransport(list(pages))
    return ArtificialAnalysisClient(
        "test-key",
        transport=transport,
        sleep=SleepRecorder(),
        uniform=upper_bound_uniform,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.01, max_delay=0.02),
        **kwargs,
    )


def full_lmarena(**overrides) -> LMArenaClient:
    """All four categories populated with one mutually-matching model."""
    splits = {
        "agent": [agent_row("Claude Opus 5 (High)")],
        "document": [rating_row("document", "claude-opus-5-high")],
        "search": [rating_row("search", "claude-opus-5-search")],
        "webdev": [rating_row("webdev", "claude-opus-5-high")],
    }
    splits.update(overrides)
    return lmarena_client(**splits)


def aa_one_model(name="Claude Opus 5 (High)", slug="claude-opus-5-high", **overrides):
    """An AA page holding one record, with a real quota snapshot on the headers."""
    return aa_page(
        [aa_model("uuid-1", slug, name, **overrides)],
        headers={"X-RateLimit-Remaining": "78", "X-RateLimit-Limit": "100", "X-AA-Tier": "free"},
    )


# --------------------------------------------------------------------------- #
# Rule 5: an empty fetch is a bad response, not an empty board
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestEmptyFetchRefuses:
    def test_empty_agent_split_fails_the_run_and_writes_nothing(self):
        """`agent` anchors every intersection, so an empty one is fatal.

        Not `partial`, and emphatically not a successful run over zero rows --
        either would let rule 4 deactivate the entire table.
        """
        # `document` loaded fine and holds a row. That row must not be written
        # either: the run aborts before the write phase, not during it.
        client = lmarena_client(
            agent=empty("agent"),
            document=[rating_row("document", "claude-opus-5-high")],
        )

        run = refresh.refresh_lmarena(client=client, use_lock=False)

        assert run.status == SyncStatus.FAILED.value
        assert LMArenaEntry.objects.count() == 0

    def test_zero_model_aa_response_fails_the_run_and_deactivates_nothing(self):
        """The specific failure mode that would blank the leaderboard."""
        refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)
        refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)
        before = LLMModel.objects.count()

        # An empty catalogue is rejected by the client itself, before parsing.
        run = refresh.refresh_aa(client=aa_client(aa_page([])), use_lock=False)

        assert run.status == SyncStatus.FAILED.value
        assert LLMModel.objects.count() == before
        assert LLMModel.objects.filter(is_active=False).count() == 0

    def test_a_failed_run_preserves_the_previous_good_data(self):
        """Rule 3: success and freshness are never conflated.

        Run 1 writes data. Run 2 fails. Every value from run 1 must survive, and
        `last_success_at` must still point at run 1 -- a failed attempt does not
        make the data stale, it makes the *run* failed.
        """
        refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)
        before = list(LMArenaEntry.objects.order_by("pk").values())
        good = refresh.store.last_success_at(Source.LMARENA.value)

        failing = lmarena_client(agent=RuntimeError("hub is down"))
        run = refresh.refresh_lmarena(client=failing, use_lock=False)

        assert run.status == SyncStatus.FAILED.value
        assert list(LMArenaEntry.objects.order_by("pk").values()) == before
        assert refresh.store.last_success_at(Source.LMARENA.value) == good


# --------------------------------------------------------------------------- #
# Rule 4: only a complete, non-empty fetch may deactivate
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestDeactivation:
    def test_a_vanished_model_is_deactivated_not_deleted(self):
        """Rule 1: there is no `DELETE` against a data table anywhere."""
        refresh.refresh_lmarena(
            client=with_categories(agent=[agent_row("A Model"), agent_row("B Model", rank=2)]),
            use_lock=False,
        )
        assert LMArenaEntry.objects.filter(category="agent", is_active=True).count() == 2

        refresh.refresh_lmarena(client=with_categories(agent=[agent_row("A Model")]), use_lock=False)

        # Both rows still exist; only the flag moved.
        assert LMArenaEntry.objects.filter(category="agent").count() == 2
        gone = LMArenaEntry.objects.get(category="agent", model_key="b-model")
        assert gone.is_active is False
        assert LMArenaEntry.objects.get(category="agent", model_key="a-model").is_active is True

    def test_a_category_that_failed_to_load_deactivates_nothing(self):
        """Rule 4, the important half: a failed field must not read as "empty".

        `webdev` throws, so we never learned what webdev holds. Deactivating its
        existing rows would turn a transient Hub outage into permanent data loss.
        """
        refresh.refresh_lmarena(
            client=with_categories(
                agent=[agent_row("A Model")],
                webdev=[rating_row("webdev", "a-model")],
            ),
            use_lock=False,
        )
        assert LMArenaEntry.objects.filter(category="webdev", is_active=True).count() == 1

        run = refresh.refresh_lmarena(
            client=with_categories(
                agent=[agent_row("A Model")], webdev=RuntimeError("hub down")
            ),
            use_lock=False,
        )

        assert run.status == SyncStatus.PARTIAL.value
        # Exactly one field failed -- with the other three loaded and empty, this
        # assertion is about `webdev` alone rather than about three missing
        # categories dressed up as evidence.
        assert run.fields_failed.keys() == {"webdev"}
        assert LMArenaEntry.objects.get(category="webdev", model_key="a-model").is_active is True

    def test_one_failing_field_still_writes_the_others(self):
        """A partial run is a success for the fields that did load."""
        run = refresh.refresh_lmarena(
            client=lmarena_client(
                agent=[agent_row("A Model")],
                document=[rating_row("document", "a-model")],
                search=RuntimeError("hub down"),
                webdev=[rating_row("webdev", "a-model")],
            ),
            use_lock=False,
        )

        assert run.status == SyncStatus.PARTIAL.value
        assert run.fields_succeeded == ["agent", "document", "webdev"]
        assert LMArenaEntry.objects.filter(is_active=True).count() == 3
        assert not LMArenaEntry.objects.filter(category="search").exists()


# --------------------------------------------------------------------------- #
# Rule 2 + idempotency
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestIdempotency:
    def test_a_second_identical_run_creates_no_rows(self):
        """Twice-daily refreshes must converge, not accumulate."""
        refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)
        first = LMArenaEntry.objects.count()

        run = refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)

        assert LMArenaEntry.objects.count() == first
        assert run.records_created == 0
        assert run.records_unchanged == first

    def test_a_changed_value_updates_rather_than_duplicating(self):
        """A rank move is an update to the one row, never a second row."""
        refresh.refresh_lmarena(client=with_categories(agent=[agent_row("A Model", rank=5)]), use_lock=False)

        refresh.refresh_lmarena(client=with_categories(agent=[agent_row("A Model", rank=2)]), use_lock=False)

        assert LMArenaEntry.objects.filter(category="agent").count() == 1
        assert LMArenaEntry.objects.get(category="agent").rank == 2

    def test_first_seen_at_is_written_once(self):
        """It records when we first saw the record, not when we last refreshed."""
        refresh.refresh_lmarena(client=with_categories(agent=[agent_row("A Model")]), use_lock=False)
        original = LMArenaEntry.objects.get(category="agent").first_seen_at

        refresh.refresh_lmarena(client=with_categories(agent=[agent_row("A Model")]), use_lock=False)

        entry = LMArenaEntry.objects.get(category="agent")
        assert entry.first_seen_at == original
        assert entry.last_synced_at >= original

    def test_a_second_identical_aa_run_creates_no_rows(self):
        refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)
        refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)
        first = LLMModel.objects.count()

        run = refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)

        assert LLMModel.objects.count() == first
        assert run.records_created == 0


# --------------------------------------------------------------------------- #
# Slug hand-offs between `aa_id`s
# --------------------------------------------------------------------------- #

# The real production case, taken from the live catalogue. AA moved the bare
# slug off the row that had been serving it and gave it to a newly created one,
# renaming the old row in the same release. `slug` is UNIQUE and the writer is
# keyed on `aa_id`, so whichever of the two rows is written first used to raise
# `IntegrityError: UNIQUE constraint failed: leaderboard_llmmodel.slug`.
OLD_AA_ID = "901ec71b-51ec-4f53-b807-06ee17b890b4"
NEW_AA_ID = "46f11cdf-1725-4abb-b39b-bd6bd948149c"
BARE_SLUG = "jt-4-1-flash-236b-a21b"
HANDOFF_NAME = "JT-4.1 Flash 236B A21B"
RENAMED_SLUG = f"{BARE_SLUG}-non-reasoning"


def _seed_bare_slug(*, slug: str = BARE_SLUG) -> None:
    """Land the pre-release state: one row holding the slug AA is about to move."""
    refresh.refresh_aa(
        client=aa_client(aa_page([aa_model(OLD_AA_ID, slug, HANDOFF_NAME)])), use_lock=False
    )


def _handoff_page(*, new_owner_first: bool) -> object:
    """The payload from the release that broke production, in either order."""
    new_owner = aa_model(NEW_AA_ID, BARE_SLUG, f"{HANDOFF_NAME} (Reasoning)")
    renamed = aa_model(OLD_AA_ID, RENAMED_SLUG, f"{HANDOFF_NAME} (Non-reasoning)")
    records = [new_owner, renamed] if new_owner_first else [renamed, new_owner]
    return aa_page(records)


@pytest.mark.django_db
class TestSlugHandoff:
    @pytest.mark.parametrize("new_owner_first", [True, False])
    def test_the_real_jt_4_1_flash_handoff_lands_in_either_order(self, new_owner_first):
        """The regression. Both orders matter: which record is written first is
        the only thing that decides whether the constraint fires, and payload
        order is AA's to choose.
        """
        _seed_bare_slug()

        run = refresh.refresh_aa(
            client=aa_client(_handoff_page(new_owner_first=new_owner_first)), use_lock=False
        )

        assert run.status == SyncStatus.SUCCESS.value
        assert LLMModel.objects.count() == 2
        assert LLMModel.objects.get(aa_id=NEW_AA_ID).slug == BARE_SLUG
        assert LLMModel.objects.get(aa_id=OLD_AA_ID).slug == RENAMED_SLUG
        assert run.summary["slugs_reassigned"] == 1
        # Both rows are still in the catalogue, so the released value is
        # transient and there is nothing to report to a human.
        assert run.summary["slugs_retired"] == 0

    def test_the_released_value_is_never_committed_for_a_row_in_the_payload(self):
        """It exists only between the release and the upsert, inside one
        transaction. If it ever reached a committed row, the value would leak
        into the API's slug space.
        """
        _seed_bare_slug()

        refresh.refresh_aa(client=aa_client(_handoff_page(new_owner_first=True)), use_lock=False)

        assert not LLMModel.objects.filter(slug__contains="-released-").exists()

    def test_a_row_dropped_from_the_payload_keeps_a_released_slug_and_is_reported(self):
        """The old owner is gone, so nothing rewrites it: its slug is committed
        in released form and a bookmark for it now resolves to the new owner.
        That is a real, reviewable event -- and the row is deactivated, never
        deleted.
        """
        _seed_bare_slug()

        refresh.refresh_aa(
            client=aa_client(aa_page([aa_model(NEW_AA_ID, BARE_SLUG, f"{HANDOFF_NAME} (Reasoning)")])),
            use_lock=False,
        )

        old = LLMModel.objects.get(aa_id=OLD_AA_ID)
        assert old.is_active is False
        assert old.slug != BARE_SLUG
        assert old.slug.startswith(BARE_SLUG)
        assert len(old.slug) <= LLMModel._meta.get_field("slug").max_length
        # Exactly one row owns the slug -- the hand-off moved it, not copied it.
        assert LLMModel.objects.filter(slug=BARE_SLUG).count() == 1
        assert LLMModel.objects.get(slug=BARE_SLUG).aa_id == NEW_AA_ID

        record = UnmatchedRecord.objects.get(
            source=Source.ARTIFICIAL_ANALYSIS.value,
            reason=UnmatchedReason.SLUG_REASSIGNED.value,
            model_key=OLD_AA_ID,
        )
        assert record.detail == {
            "old_slug": BARE_SLUG,
            "released_slug": old.slug,
            "aa_id": OLD_AA_ID,
            "claimed_by_aa_id": NEW_AA_ID,
        }

    def test_a_full_length_slug_is_released_within_the_column_width(self):
        """A 255-character slug is the worst case: `f"{slug}-released-{aa_id}"`
        would be 300 characters and the replacement itself would be refused.
        """
        longest = "j" * 255
        _seed_bare_slug(slug=longest)

        run = refresh.refresh_aa(
            client=aa_client(aa_page([aa_model(NEW_AA_ID, longest, f"{HANDOFF_NAME} (Reasoning)")])),
            use_lock=False,
        )

        assert run.status == SyncStatus.SUCCESS.value
        old = LLMModel.objects.get(aa_id=OLD_AA_ID)
        assert len(old.slug) <= 255
        assert LLMModel.objects.filter(slug=old.slug).count() == 1

    def test_the_anomaly_is_recorded_once_then_closes_stale(self):
        """Ledger semantics are current-state, not a history: the second run has
        nothing to release, so the row it did not touch is retired as no-longer-
        current rather than accumulating `occurrences` forever.
        """
        _seed_bare_slug()
        page = [aa_model(NEW_AA_ID, BARE_SLUG, f"{HANDOFF_NAME} (Reasoning)")]

        refresh.refresh_aa(client=aa_client(aa_page(page)), use_lock=False)
        second = refresh.refresh_aa(client=aa_client(aa_page(page)), use_lock=False)

        assert second.records_created == 0
        assert second.records_unchanged == 1
        assert second.summary["slugs_reassigned"] == 0
        record = UnmatchedRecord.objects.get(
            source=Source.ARTIFICIAL_ANALYSIS.value,
            reason=UnmatchedReason.SLUG_REASSIGNED.value,
            model_key=OLD_AA_ID,
        )
        assert record.occurrences == 1
        assert record.is_current is False

    @pytest.mark.parametrize("new_owner_first", [True, False])
    def test_a_steady_state_refresh_releases_nothing(self, new_owner_first):
        """The guard on `owner != holder.aa_id`. Releasing unconditionally would
        rewrite every row on every run and destroy idempotency.
        """
        _seed_bare_slug()
        refresh.refresh_aa(
            client=aa_client(_handoff_page(new_owner_first=new_owner_first)), use_lock=False
        )

        run = refresh.refresh_aa(
            client=aa_client(_handoff_page(new_owner_first=new_owner_first)), use_lock=False
        )

        assert run.summary["slugs_reassigned"] == 0
        assert run.records_created == 0
        assert run.records_unchanged == 2
        assert not LLMModel.objects.filter(slug__contains="-released-").exists()

    def test_a_dry_run_leaves_the_handoff_uncommitted(self):
        """A rehearsal rolls back, so the release must roll back with it."""
        _seed_bare_slug()

        refresh.refresh_aa(
            client=aa_client(_handoff_page(new_owner_first=True)), dry_run=True, use_lock=False
        )

        assert LLMModel.objects.count() == 1
        assert LLMModel.objects.get(aa_id=OLD_AA_ID).slug == BARE_SLUG
        assert not UnmatchedRecord.objects.filter(
            reason=UnmatchedReason.SLUG_REASSIGNED.value
        ).exists()

    def test_a_later_failure_rolls_back_the_release(self, monkeypatch):
        """The release is a write, so it belongs to the same transaction as the
        upsert that follows it. If it were outside, a crash mid-write would
        leave a row whose public slug had been taken away for nothing.
        """

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        _seed_bare_slug()
        monkeypatch.setattr(refresh.store, "upsert_aa_models", boom)

        run = refresh.refresh_aa(
            client=aa_client(_handoff_page(new_owner_first=True)), use_lock=False
        )

        assert run.status == SyncStatus.FAILED.value
        assert LLMModel.objects.count() == 1
        assert LLMModel.objects.get(aa_id=OLD_AA_ID).slug == BARE_SLUG
        assert not UnmatchedRecord.objects.filter(
            reason=UnmatchedReason.SLUG_REASSIGNED.value
        ).exists()


@pytest.mark.django_db
class TestRollback:
    def test_a_mid_write_exception_leaves_zero_rows(self, monkeypatch):
        """Rule 2: the whole write is one transaction, so it is all or nothing.

        A partially-written category would be worse than no data: it is
        indistinguishable from a complete one at read time.
        """

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(refresh.store, "upsert_lmarena_entries", boom)

        run = refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)

        assert run.status == SyncStatus.FAILED.value
        assert LMArenaEntry.objects.count() == 0
        assert UnmatchedRecord.objects.count() == 0

    def test_a_failure_rolls_back_the_ledger_too(self, monkeypatch):
        """The anomalies are written in the same transaction as the rows."""
        refresh.refresh_lmarena(client=with_categories(agent=[agent_row("A Model")]), use_lock=False)
        before = UnmatchedRecord.objects.count()

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(refresh.store, "upsert_lmarena_entries", boom)
        refresh.refresh_lmarena(
            client=lmarena_client(
                agent=[agent_row("A Model")],
                document=[rating_row("document", "not-in-agent-set")],
            ),
            use_lock=False,
        )

        assert UnmatchedRecord.objects.count() == before


# --------------------------------------------------------------------------- #
# Dry runs
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestDryRun:
    def test_a_dry_run_writes_nothing_but_still_reports(self):
        """`--dry-run` is how the match rate is measured before committing.

        The rollback means the numbers must be computed in memory and carried on
        the run row's `summary`, or the command would report zeroes.
        """
        run = refresh.refresh_lmarena(client=full_lmarena(), dry_run=True, use_lock=False)

        assert run.dry_run is True
        assert run.status == SyncStatus.SUCCESS.value
        assert LMArenaEntry.objects.count() == 0
        assert run.summary["entries"]["agent"] == 1
        assert run.summary["in_agent_set"]["document"] == 1

    def test_a_dry_aa_run_still_reports_coverage(self):
        """The rolled-back agent set is handed to AA in memory.

        Without that hand-off, `--source=all --dry-run` would report a 0% match
        rate against a database that is merely empty -- which reads as a
        catastrophic regression rather than an artifact of the rollback.
        """
        runs = refresh.refresh_all(
            lmarena_client=full_lmarena(),
            aa_client=aa_client(aa_one_model()),
            dry_run=True,
            use_lock=False,
        )

        aa_run = runs[Source.ARTIFICIAL_ANALYSIS.value]
        assert aa_run.summary["matched"] == 1
        assert aa_run.summary["matches_persisted"] is False
        assert aa_run.summary["coverage_percent"] == 100
        assert LLMModel.objects.count() == 0
        assert ModelMatch.objects.count() == 0


# --------------------------------------------------------------------------- #
# Matching persists
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestMatchingPersisted:
    def test_a_matched_pair_creates_the_join(self):
        refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)

        run = refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)

        assert run.summary["matched"] == 1
        match = ModelMatch.objects.get()
        assert match.matched_key == "claude-opus-5-high"
        assert match.lmarena_entry.category == "agent"
        assert match.model.slug == "claude-opus-5-high"
        # A model in the agent subset is retained; that flag gates
        # `/artificial-analysis/?retained=true`.
        assert match.model.is_retained is True

    def test_the_join_is_rebuilt_not_merely_added_to(self):
        """A match can *move*; the old owner must not keep a stale row.

        `OneToOneField` on both sides means the old and new owners cannot both
        hold it, which is why the rebuild is a full replacement.
        """
        refresh.refresh_lmarena(
            client=lmarena_client(
                agent=[agent_row("Claude Opus 5 (High)"), agent_row("Claude Opus 5 (Low)", rank=2)]
            ),
            use_lock=False,
        )
        refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)
        assert ModelMatch.objects.count() == 1

        # The same AA record now names the low-effort model instead.
        refresh.refresh_aa(
            client=aa_client(aa_one_model(name="Claude Opus 5 (Low)", slug="claude-opus-5-low")),
            use_lock=False,
        )

        assert ModelMatch.objects.count() == 1
        assert ModelMatch.objects.get().lmarena_entry.model_name == "Claude Opus 5 (Low)"

    def test_the_stated_effort_rung_keeps_full_confidence(self):
        """The rank->confidence mapping, end to end. Inherited from the ladder.

        `Claim.rank` gained a rung and `harness_fold` moved 4 -> 5, so the
        confidence threshold moved with it. Without this test the renumbering is
        invisible: an off-by-one would silently label the constructed-effort join
        as an inference, or promote the harness fold to 1.0, in the public API.
        """
        refresh.refresh_lmarena(
            client=lmarena_client(agent=[agent_row("Claude Opus 5 (Max)"), agent_row("Hy3", rank=2)]),
            use_lock=False,
        )
        refresh.refresh_aa(
            client=aa_client(
                aa_page(
                    [
                        aa_model(
                            "uuid-stated",
                            "claude-opus-5",
                            "Claude Opus 5 (Adaptive Reasoning, Max Effort)",
                        ),
                        # The slug carries the wrapper too, so neither the name nor
                        # the slug rung can resolve it -- only the fold can.
                        aa_model("uuid-folded", "hy3-codex-harness", "Hy3 (codex-harness)"),
                    ]
                )
            ),
            use_lock=False,
        )

        stated = ModelMatch.objects.get(match_method=MatchMethod.EXACT_EFFORT_SLUG.value)
        assert stated.matched_key == "claude-opus-5-max"
        assert stated.confidence == 1.0
        assert stated.is_manual is False

        # The other side of the threshold, so an off-by-one is caught either way.
        folded = ModelMatch.objects.get(match_method=MatchMethod.HARNESS_FOLD.value)
        assert folded.matched_key == "hy3"
        assert folded.confidence == 0.75

    def test_an_unmatched_aa_record_is_retained_only_if_it_won(self):
        """`is_retained` is membership in the agent subset, not merely "matched"."""
        refresh.refresh_lmarena(client=with_categories(agent=[agent_row("Claude Opus 5 (High)")]), use_lock=False)

        refresh.refresh_aa(
            client=aa_client(aa_page([aa_model("uuid-x", "totally-unrelated", "Unrelated Model")])),
            use_lock=False,
        )

        model = LLMModel.objects.get()
        assert model.is_retained is False
        assert UnmatchedRecord.objects.filter(
            source=Source.ARTIFICIAL_ANALYSIS.value,
            reason=UnmatchedReason.NO_LMARENA_MATCH.value,
        ).exists()


# --------------------------------------------------------------------------- #
# The agent-side ledger: the population the completeness rule drops
# --------------------------------------------------------------------------- #


def _two_agent_models(**overrides) -> LMArenaClient:
    """One agent model AA carries, one it does not."""
    return full_lmarena(
        agent=[
            agent_row("Claude Opus 5 (High)"),
            agent_row("Claude Opus 5 (Max)", rank=2),
        ],
        **overrides,
    )


def _current_by_reason() -> dict[str, int]:
    tallies: dict[str, int] = {}
    for reason in UnmatchedRecord.objects.filter(is_current=True).values_list(
        "reason", flat=True
    ):
        tallies[reason] = tallies.get(reason, 0) + 1
    return tallies


@pytest.mark.django_db
class TestAgentSideLedger:
    """`no_aa_match` is the reason a complete-looking agent row is *absent*.

    The joined endpoints drop exactly these rows, so an empty `/unmatched/` for
    this population would leave the one exclusion the frontend is guaranteed to
    notice completely unexplained -- the plan promises them "listed by name".
    """

    def test_every_agent_model_without_an_aa_match_is_recorded(self):
        refresh.refresh_lmarena(client=_two_agent_models(), use_lock=False)

        run = refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)

        assert run.summary["matched"] == 1
        assert run.summary["agent_models_unmatched"] == 1
        record = UnmatchedRecord.objects.get(
            source=Source.LMARENA.value,
            reason=UnmatchedReason.NO_AA_MATCH.value,
        )
        assert record.model_key == "claude-opus-5-max"
        assert record.model_name == "Claude Opus 5 (Max)"
        assert record.category == "agent"
        assert record.is_current is True
        # The count is what makes "AA simply lacks it" a sound conclusion rather
        # than an artefact of a partial read.
        assert record.detail["aa_records_considered"] == 1
        assert record.detail["rank"] == 2

    def test_the_matched_model_is_not_recorded_as_a_miss(self):
        refresh.refresh_lmarena(client=_two_agent_models(), use_lock=False)
        refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)

        keys = set(
            UnmatchedRecord.objects.filter(
                reason=UnmatchedReason.NO_AA_MATCH.value
            ).values_list("model_key", flat=True)
        )

        assert keys == {"claude-opus-5-max"}

    def test_a_model_that_gains_a_match_stops_being_reported(self):
        """The ledger follows the data in both directions, so a fixed problem
        does not sit in the review queue forever."""
        refresh.refresh_lmarena(client=_two_agent_models(), use_lock=False)
        refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)

        # AA now publishes the max-effort row and no longer lists the high one.
        refresh.refresh_aa(
            client=aa_client(
                aa_one_model(name="Claude Opus 5 (Max)", slug="claude-opus-5-max")
            ),
            use_lock=False,
        )

        closed = UnmatchedRecord.objects.get(
            reason=UnmatchedReason.NO_AA_MATCH.value, model_key="claude-opus-5-max"
        )
        # Closed, never deleted: the row that *was* a problem stays inspectable.
        assert closed.is_current is False
        assert closed.occurrences == 1
        assert ModelMatch.objects.get().matched_key == "claude-opus-5-max"
        # And the model AA dropped in the same run is now the miss.
        assert _current_by_reason()[UnmatchedReason.NO_AA_MATCH.value] == 1
        assert (
            UnmatchedRecord.objects.get(
                reason=UnmatchedReason.NO_AA_MATCH.value, model_key="claude-opus-5-high"
            ).is_current
            is True
        )

    def test_the_two_ledgers_do_not_close_each_others_rows(self):
        """Two phases write LMArena-sourced rows, so `close_stale` is scoped by
        reason rather than by source alone.

        The failure this pins is silent and total: an unscoped `close_stale` in
        either phase flags the other's freshly-written rows stale, and
        `/unmatched/` -- which defaults to `current=true` -- stops reporting
        them. Every assertion below is a different way to lose that population.
        """
        refresh.refresh_all(
            lmarena_client=_two_agent_models(),
            aa_client=aa_client(aa_one_model()),
            use_lock=False,
        )

        # Written moments apart by the same refresh_all, from two ledgers.
        assert _current_by_reason() == {
            UnmatchedReason.NOT_IN_AGENT_SET.value: 1,
            UnmatchedReason.NO_AA_MATCH.value: 1,
        }

        # The LMArena phase closing its own rows must not take the AA phase's.
        refresh.refresh_lmarena(client=_two_agent_models(), use_lock=False)
        assert _current_by_reason()[UnmatchedReason.NO_AA_MATCH.value] == 1

        # ...and the AA phase's agent ledger must not take the LMArena phase's.
        refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)
        assert _current_by_reason()[UnmatchedReason.NOT_IN_AGENT_SET.value] == 1
        assert _current_by_reason()[UnmatchedReason.NO_AA_MATCH.value] == 1


# --------------------------------------------------------------------------- #
# Counters
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestCounters:
    def test_duplicate_rows_are_counted_rather_than_silently_collapsed(self):
        """`webdev` really does repeat models up to 9x with conflicting ranks.

        The collapse is a large, meaningful number -- it is the evidence for why
        dedupe is mandatory, so it is surfaced rather than buried.
        """
        run = refresh.refresh_lmarena(
            client=lmarena_client(
                agent=[agent_row("A Model")],
                webdev=[
                    rating_row("webdev", "a-model", rank=3),
                    rating_row("webdev", "a-model", rank=1),
                    rating_row("webdev", "a-model", rank=2),
                ],
            ),
            use_lock=False,
        )

        assert run.records_deduplicated == 2
        assert LMArenaEntry.objects.filter(category="webdev").count() == 1
        assert LMArenaEntry.objects.get(category="webdev").rank == 1  # best rank wins

    def test_a_duplicate_is_recorded_in_the_ledger_with_both_ranks(self):
        refresh.refresh_lmarena(
            client=lmarena_client(
                agent=[agent_row("A Model")],
                webdev=[rating_row("webdev", "a-model", rank=3), rating_row("webdev", "a-model", rank=1)],
            ),
            use_lock=False,
        )

        record = UnmatchedRecord.objects.get(
            source=Source.LMARENA.value, reason=UnmatchedReason.DUPLICATE_MODEL_NAME.value
        )
        assert record.detail["kept_rank"] == 1
        assert record.detail["dropped_rank"] == 3

    def test_a_malformed_row_costs_one_record_not_the_run(self):
        """Per-row validation failure is recorded and skipped."""
        bad = agent_row("Bad Model", score="not-a-number")
        run = refresh.refresh_lmarena(
            client=with_categories(agent=[agent_row("Good Model"), bad]),
            use_lock=False,
        )

        assert run.status == SyncStatus.SUCCESS.value
        assert run.records_failed == 1
        assert LMArenaEntry.objects.filter(category="agent").count() == 1
        assert UnmatchedRecord.objects.filter(
            reason=UnmatchedReason.VALIDATION_FAILED.value
        ).exists()

    def test_a_run_that_loses_every_row_to_validation_fails(self):
        """The other half of rule 5, one level down: zero parseable rows is an
        empty board, whatever the HTTP status said."""
        bad = [agent_row(f"Bad {i}", score="nope") for i in range(3)]

        run = refresh.refresh_lmarena(client=lmarena_client(agent=bad), use_lock=False)

        assert run.status == SyncStatus.FAILED.value
        assert LMArenaEntry.objects.count() == 0


# --------------------------------------------------------------------------- #
# Quota
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestQuotaPreflight:
    def test_an_exhausted_quota_makes_zero_http_calls(self):
        """The one skip that pays for itself.

        A request we know will be refused still costs a slot in a 100/24h budget
        shared across the whole organisation, so it is not made at all.
        """
        SyncRun.objects.create(
            source=Source.ARTIFICIAL_ANALYSIS.value,
            status=SyncStatus.SUCCESS.value,
            started_at=datetime.now(tz=timezone.utc),
            rate_limit_remaining=0,
            rate_limit_reset_at=datetime.now(tz=timezone.utc) + timedelta(hours=6),
            tier="free",
        )
        transport = FakeTransport([])  # any call at all fails the test
        client = ArtificialAnalysisClient("test-key", transport=transport, sleep=SleepRecorder())

        run = refresh.refresh_aa(client=client, use_lock=False)

        assert run.status == SyncStatus.SKIPPED.value
        assert run.error_code == "rate_limit_exceeded"
        assert transport.calls == []
        # The reset time is echoed so the frontend can say when data returns.
        assert run.rate_limit_reset_at is not None

    def test_a_reset_window_that_has_passed_does_not_block(self):
        """Past the reset, the count of 0 is history, not current state."""
        SyncRun.objects.create(
            source=Source.ARTIFICIAL_ANALYSIS.value,
            status=SyncStatus.SUCCESS.value,
            started_at=datetime.now(tz=timezone.utc) - timedelta(hours=30),
            rate_limit_remaining=0,
            rate_limit_reset_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        )

        run = refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)

        assert run.status == SyncStatus.SUCCESS.value

    def test_a_skip_is_neither_a_success_nor_a_failure(self):
        """It must not refresh `last_success_at`, and must not look like an error.

        The frontend reads it as "still running" and keeps showing the previous
        data, which is exactly right: nothing changed and nothing broke.
        """
        run = refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)
        good = refresh.store.last_success_at(Source.ARTIFICIAL_ANALYSIS.value)

        # Simulate a held run lock by disabling ours and blocking the cache key.
        from django.core.cache import cache

        from leaderboard.locking import LOCK_KEY_TEMPLATE

        cache.add(LOCK_KEY_TEMPLATE.format(source=Source.ARTIFICIAL_ANALYSIS.value), "other", 60)
        skipped = refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=True)

        assert skipped.status == SyncStatus.SKIPPED.value
        assert refresh.store.last_success_at(Source.ARTIFICIAL_ANALYSIS.value) == good

    def test_rate_limit_metadata_is_persisted_for_the_frontend(self):
        run = refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)

        assert run.tier == "free"
        assert run.rate_limit_remaining == 78
        assert run.rate_limit_limit == 100
        assert run.pages_fetched == 1


# --------------------------------------------------------------------------- #
# Overlap
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestOverlapProtection:
    def test_a_second_run_skips_when_the_lock_is_held(self):
        """Skip, never queue: a queued refresh fetches the same data and spends
        a second slice of the shared quota."""
        from django.core.cache import cache

        from leaderboard.locking import LOCK_KEY_TEMPLATE

        cache.add(LOCK_KEY_TEMPLATE.format(source=Source.LMARENA.value), "other", 60)

        run = refresh.refresh_lmarena(client=full_lmarena(), use_lock=True)

        assert run.status == SyncStatus.SKIPPED.value
        assert run.error_code == "already_running"
        assert LMArenaEntry.objects.count() == 0

    def test_the_database_constraint_is_the_backstop_when_the_cache_is_lost(self):
        """Losing Redis degrades concurrency control; it does not remove it.

        `run_lock` yields "acquired" when the cache is unreachable, so the
        conditional unique index on `SyncRun` is what actually prevents the
        overlap -- and it is also what catches a stranded `running` row.
        """
        SyncRun.objects.create(
            source=Source.LMARENA.value,
            status=SyncStatus.RUNNING.value,
            started_at=datetime.now(tz=timezone.utc),
        )

        run = refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)

        assert run.status == SyncStatus.SKIPPED.value
        assert run.error_code == "already_running"
        assert LMArenaEntry.objects.count() == 0

    def test_a_stale_running_row_is_reaped_rather_than_blocking_forever(self):
        """One SIGKILLed worker must not block every future refresh, permanently."""
        stranded = SyncRun.objects.create(
            source=Source.LMARENA.value,
            status=SyncStatus.RUNNING.value,
            started_at=datetime.now(tz=timezone.utc) - timedelta(hours=7),
        )

        run = refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)

        assert run.status == SyncStatus.SUCCESS.value
        stranded.refresh_from_db()
        assert stranded.status == SyncStatus.FAILED.value
        assert stranded.error_code == "reaped"

    def test_the_combined_refresh_takes_one_outer_lock(self):
        """`refresh_all` holds a single lock across both sources and re-enters
        each with locking disabled, so it cannot deadlock against itself."""
        from django.core.cache import cache

        from leaderboard.locking import LOCK_KEY_TEMPLATE

        cache.add(LOCK_KEY_TEMPLATE.format(source=refresh.ALL_SOURCES_LOCK), "other", 60)

        runs = refresh.refresh_all(
            lmarena_client=full_lmarena(), aa_client=aa_client(aa_one_model()), use_lock=True
        )

        assert {run.status for run in runs.values()} == {SyncStatus.SKIPPED.value}
        assert LMArenaEntry.objects.count() == 0

    def test_the_lock_is_released_after_a_failed_run(self):
        """Otherwise a single failure would block every later refresh."""
        refresh.refresh_lmarena(client=lmarena_client(agent=RuntimeError("down")), use_lock=True)

        run = refresh.refresh_lmarena(client=full_lmarena(), use_lock=True)

        assert run.status == SyncStatus.SUCCESS.value


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestRefreshAll:
    def test_lmarena_runs_first_because_aa_depends_on_it(self):
        """AA's retention and matching both read the agent set.

        Dispatching them as independent tasks would let AA read a stale agent
        set on a cold database and retain nothing.
        """
        runs = refresh.refresh_all(
            lmarena_client=full_lmarena(),
            aa_client=aa_client(aa_one_model()),
            use_lock=False,
        )

        assert runs[Source.LMARENA.value].status == SyncStatus.SUCCESS.value
        assert runs[Source.ARTIFICIAL_ANALYSIS.value].status == SyncStatus.SUCCESS.value
        assert ModelMatch.objects.count() == 1

    def test_a_failed_lmarena_run_still_attempts_aa(self):
        """AA is independently useful -- its rows are served by
        `/artificial-analysis/` with no LMArena counterpart required."""
        runs = refresh.refresh_all(
            lmarena_client=lmarena_client(agent=RuntimeError("hub down")),
            aa_client=aa_client(aa_one_model()),
            use_lock=False,
        )

        assert runs[Source.LMARENA.value].status == SyncStatus.FAILED.value
        assert runs[Source.ARTIFICIAL_ANALYSIS.value].status == SyncStatus.SUCCESS.value
        assert LLMModel.objects.count() == 1
        assert ModelMatch.objects.count() == 0

    def test_the_run_clock_is_shared_across_both_sources(self):
        """One `synced_at` for the pair, so the two halves of a refresh agree on
        when "now" was and the freshness block has one timestamp to report."""
        when = datetime(2026, 9, 11, 4, 0, tzinfo=timezone.utc)

        runs = refresh.refresh_all(
            lmarena_client=full_lmarena(),
            aa_client=aa_client(aa_one_model()),
            synced_at=when,
            use_lock=False,
        )

        assert runs[Source.LMARENA.value].started_at is not None
        # `full_lmarena` writes the same key in three categories, so scope by
        # category rather than taking the only row.
        assert LMArenaEntry.objects.get(category="agent").last_synced_at == when
        assert LLMModel.objects.get().last_synced_at == when


# --------------------------------------------------------------------------- #
# Type discipline, end to end
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestStoredTypes:
    def test_money_is_decimal_and_indices_are_float_in_the_database(self):
        """The source contract survives the write, not just the parse."""
        refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)
        refresh.refresh_aa(
            client=aa_client(
                aa_page(
                    [
                        aa_model(
                            "uuid-1",
                            "claude-opus-5-high",
                            "Claude Opus 5 (High)",
                            artificial_analysis_intelligence_index_cost={
                                "total_cost": 59.99,
                                "cost_per_task": {"total_cost": 0.0502},
                            },
                            evaluations={"artificial_analysis_intelligence_index": 42.5},
                        )
                    ]
                )
            ),
            use_lock=False,
        )

        model = LLMModel.objects.get()
        assert model.cost_per_task == Decimal("0.0502")
        assert model.intelligence_index_total_cost == Decimal("59.99")
        assert isinstance(model.intelligence_index, float)

    def test_a_null_metric_is_stored_as_null_not_zero(self):
        """The rule that keeps every cost and latency chart honest.

        A zero here draws a real data point at the origin, which reads as "this
        model is free" or "this model responds instantly".
        """
        refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)
        refresh.refresh_aa(client=aa_client(aa_one_model()), use_lock=False)

        model = LLMModel.objects.get()
        assert model.cost_per_task is None
        assert model.median_time_to_first_token_seconds is None
        assert model.coding_index is None

    def test_the_raw_payload_is_kept_for_troubleshooting(self):
        refresh.refresh_lmarena(client=full_lmarena(), use_lock=False)
        refresh.refresh_aa(
            client=aa_client(aa_one_model(release_date="2026-05-04")), use_lock=False
        )

        model = LLMModel.objects.get()
        assert model.raw_payload["release_date"] == "2026-05-04"
        assert model.release_date.isoformat() == "2026-05-04"
