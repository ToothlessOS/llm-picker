"""The discussion refresh service: budgets, the refetch gate, and the prune.

The cases that matter most here are the ones about *not* destroying data and about
not spending requests twice. `refresh.py`'s suite already establishes the shape of
those guarantees for a source that deactivates; this one has to establish them for
a source that deletes, which is why `TestAgeOutPrune` exists at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from leaderboard.clients.exceptions import EmptyResponseError
from leaderboard.constants import EntityKind, MatchMode, Source, SyncStatus
from leaderboard.models import (
    DiscussionTag,
    HNComment,
    HNThread,
    ProviderAlias,
    ProviderEntity,
    SyncRun,
)
from leaderboard.services import discussions
from leaderboard.tests.fakes import (
    DEFAULT_HN_TIMESTAMP,
    FakeHNClient,
    hn_comment,
    hn_item,
    hn_story_hit,
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clear_relevance_cache():
    """`_relevance_index` is `lru_cache`d, so a test that changed the vocabulary
    would leak into the next one."""
    discussions._relevance_index.cache_clear()
    yield
    discussions._relevance_index.cache_clear()


def story(hn_id: int, title: str, **overrides) -> dict:
    """An LLM-related story that clears the bank's floors.

    The defaults must stay **above** `sweep_min_comments`: the prune treats a
    thread below the floor as out of policy and deletes it in the same
    transaction that stored it, so a fixture using a smaller number would make
    every test about *something else* fail for a reason it does not mention.
    Tests that deliberately go below the floor say so explicitly.
    """
    overrides.setdefault("points", 300)
    overrides.setdefault("num_comments", 100)
    overrides.setdefault("created_at_i", int(NOW.timestamp()) - 3600)
    return hn_story_hit(hn_id, title, **overrides)


def tree(hn_id: int, *, children=None) -> dict:
    return hn_item(hn_id, title="Thread", children=children or [])


def run(client, **overrides):
    overrides.setdefault("now", NOW)
    overrides.setdefault("synced_at", NOW)
    return discussions.refresh_discussions(client=client, use_lock=False, **overrides)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


class TestWindowSlices:
    def test_covers_the_window_with_the_configured_slice_width(self):
        slices = discussions.window_slices(now=NOW, window_days=14, slice_days=7)

        assert slices == [
            (int(NOW.timestamp()) - 7 * 86400, int(NOW.timestamp())),
            (int(NOW.timestamp()) - 14 * 86400, int(NOW.timestamp()) - 7 * 86400),
        ]

    def test_slices_are_contiguous_and_never_overlap(self):
        """A gap would leave days unqueried while the run still looked exhaustive."""
        slices = discussions.window_slices(now=NOW, window_days=14, slice_days=3)

        for newer, older in zip(slices, slices[1:]):
            assert older[1] == newer[0]

    def test_the_newest_slice_comes_first(self):
        """So a run cut short has covered the days a reader is likeliest to want."""
        slices = discussions.window_slices(now=NOW, window_days=6, slice_days=2)

        assert slices[0][1] == int(NOW.timestamp())

    def test_the_oldest_slice_reaches_the_full_window(self):
        slices = discussions.window_slices(now=NOW, window_days=14, slice_days=7)

        assert slices[-1][0] == int(NOW.timestamp()) - 14 * 86400

    @pytest.mark.parametrize("slice_days", [0, -1])
    def test_a_non_positive_slice_is_refused(self, slice_days):
        with pytest.raises(ValueError):
            discussions.window_slices(now=NOW, window_days=14, slice_days=slice_days)


class TestMergeHits:
    def test_dedupes_a_story_found_by_both_streams(self):
        """Keyed on the HN item id, which is also the thread's upsert key."""
        hit = story(1, "LLM news")

        merged = discussions.merge_hits(
            window=FakeHNClient._result([hit]),
            sweeps=[FakeHNClient._result([hit])],
        )

        assert list(merged) == [1]
        assert merged[1].streams == [discussions.STREAM_KEYWORD, discussions.STREAM_WINDOW]

    def test_keeps_stories_only_one_stream_found(self):
        merged = discussions.merge_hits(
            window=FakeHNClient._result([story(1, "LLM one")]),
            sweeps=[FakeHNClient._result([story(2, "Claude news")])],
        )

        assert sorted(merged) == [1, 2]
        assert merged[2].streams == [discussions.STREAM_KEYWORD]

    def test_skips_an_unparseable_hit_without_losing_the_rest(self):
        """One malformed entry must not cost a whole window."""
        merged = discussions.merge_hits(
            window=FakeHNClient._result([{"no": "id"}, story(1, "LLM")]),
            sweeps=[],
        )

        assert list(merged) == [1]


class TestSelectCandidates:
    def _discovered(self, *hits):
        return discussions.merge_hits(window=FakeHNClient._result(list(hits)), sweeps=[])

    def test_drops_a_story_that_fires_no_relevance_term(self):
        candidates, dropped = discussions.select_candidates(
            discovered=self._discovered(story(1, "LLM news"), story(2, "Best laptop 2026")),
            relevance=discussions._relevance_index(),
            comment_weight=1.0,
        )

        assert [c.story.hn_id for c in candidates] == [1]
        assert dropped == 1

    def test_ranks_by_points_plus_weighted_comments(self):
        candidates, _ = discussions.select_candidates(
            discovered=self._discovered(
                story(1, "LLM quiet", points=100, num_comments=0),
                story(2, "LLM busy", points=100, num_comments=50),
            ),
            relevance=discussions._relevance_index(),
            comment_weight=1.0,
        )

        assert [c.story.hn_id for c in candidates] == [2, 1]

    def test_an_unreported_count_contributes_nothing_rather_than_a_zero(self):
        """`points=None` means "not reported", which is not "no upvotes"."""
        assert discussions.rank_score(
            discussions.parse_story_hit(story(1, "LLM", points=None, num_comments=10)),
            comment_weight=1.0,
        ) == 10.0

    def test_ties_break_deterministically(self):
        """So two runs cannot disagree about which threads the tree budget reaches."""
        candidates, _ = discussions.select_candidates(
            discovered=self._discovered(
                story(1, "LLM a", points=10, num_comments=0),
                story(2, "LLM b", points=10, num_comments=0),
            ),
            relevance=discussions._relevance_index(),
            comment_weight=1.0,
        )

        assert [c.story.hn_id for c in candidates] == [2, 1]

    def test_records_the_terms_that_fired(self):
        candidates, _ = discussions.select_candidates(
            discovered=self._discovered(story(1, "Claude and GPT-5")),
            relevance=discussions._relevance_index(),
            comment_weight=1.0,
        )

        assert "claude" in candidates[0].terms
        assert "gpt" in candidates[0].terms


class TestSweepTerms:
    def test_sweeps_a_window_of_terms(self):
        terms, cursor = discussions.sweep_terms(cursor=0, budget=3)

        assert terms == list(discussions.HN_SWEEP_TERMS[:3])
        assert cursor == 3

    def test_wraps_around_the_vocabulary(self):
        total = len(discussions.HN_SWEEP_TERMS)
        terms, cursor = discussions.sweep_terms(cursor=total - 1, budget=3)

        assert terms[0] == discussions.HN_SWEEP_TERMS[total - 1]
        assert terms[1] == discussions.HN_SWEEP_TERMS[0]
        assert cursor == 2

    def test_a_zero_budget_spends_nothing_and_keeps_the_cursor(self):
        terms, cursor = discussions.sweep_terms(cursor=5, budget=0)

        assert terms == []
        assert cursor == 5

    def test_cost_is_constant_however_large_the_vocabulary_grows(self):
        """The whole reason for round-robin rather than sweeping everything."""
        terms, _ = discussions.sweep_terms(cursor=0, budget=4)

        assert len(terms) == 4
        assert len(terms) < len(discussions.HN_SWEEP_TERMS)


@pytest.mark.django_db
class TestKeywordCursor:
    def test_defaults_to_the_start_of_the_vocabulary(self):
        assert discussions.keyword_cursor() == 0

    def test_resumes_from_the_last_successful_run(self):
        SyncRun.objects.create(
            source=Source.HACKERNEWS.value,
            status=SyncStatus.SUCCESS.value,
            started_at=NOW,
            finished_at=NOW,
            summary={"keyword_cursor": 7},
        )

        assert discussions.keyword_cursor() == 7

    def test_ignores_a_dry_run(self):
        """A rehearsal writes nothing, so its cursor is not a fact either."""
        SyncRun.objects.create(
            source=Source.HACKERNEWS.value,
            status=SyncStatus.SUCCESS.value,
            dry_run=True,
            started_at=NOW,
            finished_at=NOW,
            summary={"keyword_cursor": 7},
        )

        assert discussions.keyword_cursor() == 0

    def test_ignores_a_failed_run(self):
        SyncRun.objects.create(
            source=Source.HACKERNEWS.value,
            status=SyncStatus.FAILED.value,
            started_at=NOW,
            finished_at=NOW,
            summary={"keyword_cursor": 7},
        )

        assert discussions.keyword_cursor() == 0

    def test_survives_a_malformed_summary(self):
        SyncRun.objects.create(
            source=Source.HACKERNEWS.value,
            status=SyncStatus.SUCCESS.value,
            started_at=NOW,
            finished_at=NOW,
            summary={"keyword_cursor": "not a number"},
        )

        assert discussions.keyword_cursor() == 0


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestRefreshHappyPath:
    def test_stores_the_thread_its_comments_and_their_positions(self):
        client = FakeHNClient(
            window_hits=[story(11, "Muse Spark Open (meta.ai)")],
            items={11: tree(11, children=[hn_comment(21, text="top"), hn_comment(22, parent=None, text="reply")])},
        )

        result = run(client)

        assert result.status == SyncStatus.SUCCESS.value
        thread = HNThread.objects.get(hn_id=11)
        assert thread.title == "Muse Spark Open (meta.ai)"
        assert thread.comments_stored == 2
        assert thread.fetched_at is not None
        assert sorted(HNComment.objects.filter(thread=thread).values_list("hn_id", flat=True)) == [21, 22]

    def test_queries_the_window_in_slices(self):
        """One query per slice, so no single query can meet the pagination ceiling."""
        client = FakeHNClient(window_hits=[story(11, "LLM")])

        run(client)

        assert len(client.window_calls) == 2  # 14 days / 7-day slices

    def test_spends_the_keyword_budget(self):
        client = FakeHNClient(window_hits=[story(11, "LLM")])

        run(client)

        assert len(client.term_calls) == discussions.hn_config().keyword_query_budget

    def test_records_a_summary_an_operator_can_read(self):
        client = FakeHNClient(window_hits=[story(11, "LLM"), story(12, "laptop review")], items={11: tree(11)})

        result = run(client)

        assert result.summary["llm_related"] == 1
        assert result.summary["dropped_irrelevant"] == 1
        assert result.summary["trees_fetched"] == 1
        assert result.summary["comments_stored"] == 0
        assert "keyword_cursor" in result.summary

    def test_a_second_identical_run_changes_only_bookkeeping(self):
        """The idempotency contract: rows are upserted, not appended."""
        hits = [story(11, "LLM")]
        items = {11: tree(11, children=[hn_comment(21, text="hello")])}

        run(FakeHNClient(window_hits=hits, items=items))
        first = HNComment.objects.get(hn_id=21)
        first_seen = first.first_seen_at

        run(FakeHNClient(window_hits=hits, items=items))

        assert HNComment.objects.count() == 1
        refreshed = HNComment.objects.get(hn_id=21)
        assert refreshed.first_seen_at == first_seen
        assert refreshed.text_plain == "hello"

    def test_no_comment_tree_is_fetched_twice_when_nothing_changed(self):
        hits = [story(11, "LLM", num_comments=6)]
        items = {11: tree(11, children=[hn_comment(21)])}
        run(FakeHNClient(window_hits=hits, items=items))

        client = FakeHNClient(window_hits=hits, items=items)
        result = run(client)

        assert client.item_calls == []
        assert result.summary["trees_unchanged"] == 1

    def test_a_thread_that_gained_comments_is_refetched(self):
        run(FakeHNClient(window_hits=[story(11, "LLM", num_comments=6)], items={11: tree(11, children=[hn_comment(21)])}))

        client = FakeHNClient(
            window_hits=[story(11, "LLM", num_comments=7)],
            items={11: tree(11, children=[hn_comment(21), hn_comment(22)])},
        )
        result = run(client)

        assert client.item_calls == [11]
        assert result.summary["trees_fetched"] == 1
        assert HNComment.objects.count() == 2

    def test_merges_which_stream_found_a_thread(self):
        """A thread found by the window query last hour and the keyword sweep this
        hour was found by both, and collapsing that to whichever ran last would
        lose the record of how it was discovered."""
        hit = story(11, "LLM")
        # Run 1: only the keyword sweep sees it (the window returns nothing).
        run(FakeHNClient(term_hits={"llm": [hit]}, items={11: tree(11)}))
        assert HNThread.objects.get(hn_id=11).source_metadata["discovered_by"] == ["keyword"]

        # Run 2: the window sees it. The sweep window has rotated past `llm`, so
        # the keyword provenance can only have survived by being merged.
        run(FakeHNClient(window_hits=[hit], items={11: tree(11)}))

        metadata = HNThread.objects.get(hn_id=11).source_metadata
        assert metadata["discovered_by"] == ["keyword", "window"]

    def test_keeps_provenance_of_the_hit(self):
        client = FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)})

        run(client)

        hit = HNThread.objects.get(hn_id=11).source_metadata["hit"]
        assert hit["title"] == "LLM"
        # Algolia's own scoring blobs are dropped; they dwarf the record.
        assert all(not str(key).startswith("_") for key in hit)


@pytest.fixture
def anthropic() -> ProviderEntity:
    """A vocabulary of exactly one vendor, so the assertions mean something.

    The seeded vocabulary is removed first. It ships with the migration, so a
    test that did not clear it would be asserting against 57 aliases whose
    contents are not this file's business -- and a change to the seed would
    silently change the expected tag counts here.
    """
    ProviderAlias.objects.all().delete()
    ProviderEntity.objects.all().delete()

    vendor = ProviderEntity.objects.create(
        slug="anthropic",
        label="Anthropic",
        kind=EntityKind.VENDOR,
        lmarena_organization="anthropic",
    )
    ProviderAlias.objects.create(
        entity=vendor, alias_text="Anthropic", alias_key="anthropic", match_mode=MatchMode.WORD
    )
    ProviderAlias.objects.create(
        entity=vendor, alias_text="Claude", alias_key="claude", match_mode=MatchMode.TOKEN_PREFIX
    )
    return vendor


@pytest.mark.django_db
class TestTagging:
    def test_tags_from_the_title(self, anthropic):
        client = FakeHNClient(window_hits=[story(11, "Anthropic ships something")], items={11: tree(11)})

        run(client)

        tag = DiscussionTag.objects.get(thread__hn_id=11)
        assert tag.entity == anthropic
        assert tag.comment is None
        assert tag.matched_text == "Anthropic"

    def test_tags_from_a_comment_with_the_alias_that_fired(self, anthropic):
        client = FakeHNClient(
            window_hits=[story(11, "LLM thread")],
            items={11: tree(11, children=[hn_comment(21, text="I use Claude daily")])},
        )

        run(client)

        tag = DiscussionTag.objects.get(thread__hn_id=11)
        assert tag.comment.hn_id == 21
        assert tag.matched_text == "Claude"

    def test_tags_are_rebuilt_rather_than_appended(self, anthropic):
        """A tag is derived data, so an alias that stopped matching must not linger.

        Applied with `--skip-discovery`, which forces a refetch -- see
        `test_a_withdrawn_alias_survives_until_a_forced_refetch` for why that is
        the documented route rather than something the hourly run does.
        """
        client = FakeHNClient(window_hits=[story(11, "Anthropic")], items={11: tree(11)})
        run(client)
        assert DiscussionTag.objects.count() == 1

        # The alias is withdrawn; a forced refetch must leave no tag behind.
        ProviderAlias.objects.all().delete()
        run(FakeHNClient(items={11: tree(11)}), skip_discovery=True)

        assert DiscussionTag.objects.count() == 0

    def test_a_withdrawn_title_alias_goes_on_the_next_ordinary_run(self, anthropic):
        """Title tags are rebuilt every run, tree or no tree.

        It costs one matcher call per thread, and skipping it would leave a thread
        whose tree was deferred this hour with no tags at all -- not even the one
        its own title earned.
        """
        run(FakeHNClient(window_hits=[story(11, "Anthropic")], items={11: tree(11)}))
        assert DiscussionTag.objects.count() == 1

        ProviderAlias.objects.all().delete()
        run(FakeHNClient(window_hits=[story(11, "Anthropic")], items={11: tree(11)}))

        assert DiscussionTag.objects.count() == 0

    def test_a_withdrawn_comment_alias_survives_until_a_forced_refetch(self, anthropic):
        """The boundary, pinned rather than left accidental.

        Comment tags are rebuilt only for threads whose tree was fetched, because
        the alternative -- re-matching every stored comment of every stored thread
        on every hourly run -- means loading a few hundred thousand comment rows
        into memory each hour to redo work that has not changed.

        So a change to a *comment* alias reaches an existing thread through
        `manage.py refresh_discussions --skip-discovery`, which forces the refetch.
        The hourly run picks it up for any thread whose comment count moves, which
        is most active ones.
        """
        run(
            FakeHNClient(
                window_hits=[story(11, "LLM thread", num_comments=6)],
                items={11: tree(11, children=[hn_comment(21, text="I use Claude")])},
            )
        )
        assert DiscussionTag.objects.filter(comment__isnull=False).count() == 1

        ProviderAlias.objects.filter(alias_key="claude").delete()
        # An ordinary hourly run: the comment count is unchanged, so no refetch and
        # the old comment tag stands.
        run(
            FakeHNClient(
                window_hits=[story(11, "LLM thread", num_comments=6)],
                items={11: tree(11, children=[hn_comment(21, text="I use Claude")])},
            )
        )

        assert DiscussionTag.objects.filter(comment__isnull=False).count() == 1

        # A forced refetch clears it.
        run(
            FakeHNClient(items={11: tree(11, children=[hn_comment(21, text="I use Claude")])}),
            skip_discovery=True,
        )

        assert DiscussionTag.objects.filter(comment__isnull=False).count() == 0

    def test_a_thread_with_no_fetched_tree_still_gets_its_title_tags(self, anthropic):
        """A regression the first live run found: tagging lived inside the
        "tree was fetched" branch, so 461 threads came back with no tags at all --
        not even the ones their own titles earned."""
        hits = [story(100 + index, "Anthropic thread") for index in range(3)]
        items = {100 + index: tree(100 + index) for index in range(3)}

        run(FakeHNClient(window_hits=hits, items=items), max_trees=1)

        assert HNThread.objects.count() == 3
        assert DiscussionTag.objects.filter(comment__isnull=True).count() == 3

    def test_a_thread_with_no_alias_match_gets_no_tags(self):
        run(FakeHNClient(window_hits=[story(11, "LLM thread")], items={11: tree(11)}))

        assert DiscussionTag.objects.count() == 0

    def test_overlapping_aliases_for_one_entity_yield_one_tag(self, anthropic):
        """A regression the first live run found.

        `"Anthropic Claude"` fires both the `anthropic` and the `claude` alias, and
        both point at the same entity -- so two tags for one `(thread, comment,
        entity)` would violate the uniqueness constraint that keeps a tag
        unambiguous.
        """
        client = FakeHNClient(
            window_hits=[story(11, "LLM thread")],
            items={11: tree(11, children=[hn_comment(21, text="Anthropic Claude is good")])},
        )

        run(client)

        assert DiscussionTag.objects.filter(thread__hn_id=11).count() == 1

    def test_the_longest_matching_spelling_is_the_one_recorded(self, anthropic):
        """The most specific spelling is the most useful thing to show a reviewer
        asking why a thread is tagged."""
        ProviderAlias.objects.create(
            entity=anthropic,
            alias_text="Anthropic Claude",
            alias_key="anthropic-claude",
            match_mode=MatchMode.TOKEN_RUN,
        )
        client = FakeHNClient(window_hits=[story(11, "Anthropic Claude")], items={11: tree(11)})

        run(client)

        assert DiscussionTag.objects.get(thread__hn_id=11).matched_text == "Anthropic Claude"


def stored_thread(hn_id: int, **overrides) -> HNThread:
    """A thread already in the bank, without spending a refresh to create it."""
    posted = NOW - timedelta(days=1)
    fields = {
        "title": "Stored thread",
        "posted_at": posted,
        "first_seen_at": posted,
        "last_synced_at": posted,
        "fetched_at": posted,
        "comments_stored": 1,
        # Above the sweep floor, so the prune is never the thing under test.
        "points": 500,
        "num_comments": 100,
    }
    fields.update(overrides)
    return HNThread.objects.create(hn_id=hn_id, **fields)


def stored_comment(thread: HNThread, hn_id: int, **overrides) -> HNComment:
    seen = NOW - timedelta(days=2)
    fields = {
        "thread": thread,
        "hn_id": hn_id,
        "path": "000000",
        "first_seen_at": seen,
        "last_synced_at": seen,
    }
    fields.update(overrides)
    return HNComment.objects.create(**fields)


@pytest.mark.django_db
class TestCommentsMovedBetweenStories:
    """Hacker News merges duplicate stories and reassigns their comments.

    A comment can therefore appear in a tree whose thread is not the one holding
    its row. `hn_id` is globally unique, so treating it as new raises
    `UNIQUE constraint failed: leaderboard_hncomment.hn_id` and -- because the
    whole write phase shares one transaction -- fails the entire run.
    """

    def test_a_comment_stored_under_another_thread_is_moved_not_reinserted(self):
        old = stored_thread(101)
        original = stored_comment(old, 500, text_plain="old")
        pk, first_seen = original.pk, original.first_seen_at

        result = run(
            FakeHNClient(
                window_hits=[story(102, "LLM thread")],
                items={102: tree(102, children=[hn_comment(500, text="new")])},
            )
        )

        assert result.status == SyncStatus.SUCCESS.value
        assert result.error_message == ""
        assert result.summary["comments_created"] == 0
        assert result.summary["comments_updated"] == 1
        assert result.summary["comments_reassigned"] == 1

        moved = HNComment.objects.get(hn_id=500)
        assert moved.pk == pk
        assert moved.first_seen_at == first_seen
        assert moved.thread.hn_id == 102
        assert moved.text_plain == "new"
        assert not HNComment.objects.filter(thread=old).exists()

    def test_a_moved_comment_loses_its_old_thread_tags_and_gains_the_new_threads(
        self, anthropic
    ):
        old = stored_thread(101)
        comment = stored_comment(
            old, 500, text_html="<p>Claude</p>", text_plain="Claude"
        )
        DiscussionTag.objects.create(
            thread=old,
            comment=comment,
            entity=anthropic,
            matched_text="Claude",
            match_mode=MatchMode.TOKEN_PREFIX,
            mentions=1,
            first_seen_at=NOW,
            last_synced_at=NOW,
        )

        run(
            FakeHNClient(
                window_hits=[story(102, "LLM thread")],
                items={102: tree(102, children=[hn_comment(500, text="Claude")])},
            )
        )

        row = HNComment.objects.get(hn_id=500)
        tags = list(DiscussionTag.objects.filter(comment=row).select_related("thread"))
        assert [tag.thread.hn_id for tag in tags] == [102]
        assert not DiscussionTag.objects.filter(thread=old, comment__isnull=False).exists()

    def test_a_duplicate_comment_id_in_one_tree_is_stored_once(self):
        result = run(
            FakeHNClient(
                window_hits=[story(11, "LLM")],
                items={
                    11: tree(
                        11,
                        children=[
                            hn_comment(21, text="first"),
                            hn_comment(21, text="second"),
                        ],
                    )
                },
            )
        )

        assert result.status == SyncStatus.SUCCESS.value
        assert HNComment.objects.filter(hn_id=21).count() == 1
        assert HNComment.objects.get(hn_id=21).text_plain == "first"
        assert result.summary["comments_stored"] == 1
        assert result.summary["comments_created"] == 1

    def test_a_duplicated_id_owned_by_another_thread_is_moved_once(self):
        old = stored_thread(101)
        stored_comment(old, 500)

        run(
            FakeHNClient(
                window_hits=[story(102, "LLM thread")],
                items={102: tree(102, children=[hn_comment(500), hn_comment(500)])},
            )
        )

        assert HNComment.objects.filter(hn_id=500).count() == 1
        assert HNComment.objects.get(hn_id=500).thread.hn_id == 102

    def test_a_moved_parent_is_visible_when_reparenting_its_moved_child(self):
        """The reassignment has to be flushed before the parent map is re-read,
        or the child's FK is silently nulled during the move."""
        old = stored_thread(101)
        parent = stored_comment(old, 500)
        stored_comment(
            old,
            501,
            path="000000.000000",
            depth=1,
            parent=parent,
            parent_hn_id=500,
        )

        run(
            FakeHNClient(
                window_hits=[story(102, "LLM thread")],
                items={102: tree(102, children=[hn_comment(500, children=[hn_comment(501)])])},
            )
        )

        assert HNComment.objects.get(hn_id=500).thread.hn_id == 102
        child = HNComment.objects.get(hn_id=501)
        assert child.thread.hn_id == 102
        assert child.parent_id == parent.pk

    def test_a_comment_moved_out_of_a_pruned_thread_survives(self):
        old = stored_thread(101, points=1, num_comments=1)
        stored_comment(old, 500)

        result = run(
            FakeHNClient(
                window_hits=[story(102, "LLM thread")],
                items={102: tree(102, children=[hn_comment(500)])},
            )
        )

        assert result.summary["threads_pruned"] >= 1
        assert not HNThread.objects.filter(hn_id=101).exists()
        assert HNComment.objects.get(hn_id=500).thread.hn_id == 102


@pytest.mark.django_db
class TestFailureHandling:
    def test_a_failed_window_leaves_the_bank_untouched(self):
        run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}))
        before = HNThread.objects.get(hn_id=11).last_synced_at

        result = run(FakeHNClient(window_error=EmptyResponseError("no stories")))

        assert result.status == SyncStatus.FAILED.value
        assert HNThread.objects.get(hn_id=11).last_synced_at == before

    def test_one_failed_tree_finishes_partial_and_keeps_the_old_tree(self):
        """The rest of the bank is still good; one thread must not fail the run."""
        run(FakeHNClient(window_hits=[story(11, "LLM", num_comments=6)], items={11: tree(11, children=[hn_comment(21)])}))

        client = FakeHNClient(
            window_hits=[story(11, "LLM", num_comments=9)],
            fail_items={11},
        )
        result = run(client)

        assert result.status == SyncStatus.PARTIAL.value
        assert result.summary["trees_failed"] == 1
        # The stored tree survived, because the write phase skips a thread whose
        # fetch failed rather than clearing it.
        assert HNComment.objects.filter(thread__hn_id=11).count() == 1

    def test_an_oversize_thread_is_refused_before_a_request_is_spent(self):
        client = FakeHNClient(
            window_hits=[story(11, "LLM", num_comments=99_999)],
            items={11: tree(11)},
        )

        result = run(client)

        assert result.summary["trees_skipped_oversize"] == 1
        assert client.item_calls == []
        # It is still a thread in the bank, just one with no comments stored.
        assert HNThread.objects.filter(hn_id=11).exists()

    def test_the_run_budget_defers_rather_than_overrunning(self):
        """An hourly job that overran its own interval would collide with itself."""
        hits = [story(100 + index, "LLM") for index in range(5)]
        items = {100 + index: tree(100 + index) for index in range(5)}
        ticks = iter([0.0] + [1000.0] * 10)

        result = run(
            FakeHNClient(window_hits=hits, items=items),
            monotonic=lambda: next(ticks, 1000.0),
            max_trees=5,
        )

        assert result.summary["trees_deferred"] >= 1

    def test_the_tree_budget_defers_the_rest(self):
        hits = [story(100 + index, "LLM", points=1000 - index) for index in range(5)]
        items = {100 + index: tree(100 + index) for index in range(5)}

        result = run(FakeHNClient(window_hits=hits, items=items), max_trees=2)

        assert result.summary["trees_fetched"] == 2
        assert result.summary["trees_deferred"] == 3

    def test_the_highest_ranked_threads_get_the_budget_first(self):
        hits = [
            story(1, "LLM low", points=1, num_comments=50),
            story(2, "LLM high", points=900, num_comments=50),
        ]
        items = {1: tree(1), 2: tree(2)}

        client = FakeHNClient(window_hits=hits, items=items)
        run(client, max_trees=1)

        assert client.item_calls == [2]


@pytest.mark.django_db
class TestAgeOutPrune:
    def _old_thread(self, hn_id: int, *, days: int, **overrides) -> HNThread:
        posted = NOW - timedelta(days=days)
        fields = {
            "title": "old",
            "posted_at": posted,
            "first_seen_at": posted,
            "last_synced_at": posted,
            "fetched_at": posted,
            "comments_stored": 1,
            # Above the sweep floor by default, so a test that is about *age*
            # is not accidentally also about the floor.
            "points": 500,
            "num_comments": 100,
        }
        fields.update(overrides)
        return HNThread.objects.create(hn_id=hn_id, **fields)

    def test_a_thread_outside_the_window_is_deleted_with_its_comments(self):
        old = self._old_thread(999, days=30)
        HNComment.objects.create(
            thread=old,
            hn_id=888,
            path="000000",
            first_seen_at=NOW,
            last_synced_at=NOW,
        )

        result = run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}))

        assert result.summary["threads_pruned"] == 1
        assert not HNThread.objects.filter(hn_id=999).exists()
        assert not HNComment.objects.filter(hn_id=888).exists()

    def test_a_thread_inside_the_window_survives(self):
        self._old_thread(998, days=13)

        run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}))

        assert HNThread.objects.filter(hn_id=998).exists()

    def test_the_prune_is_counted_as_a_removal(self):
        """So `/metadata/`'s per-run counters can describe an HN run at all."""
        self._old_thread(999, days=30)

        result = run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}))

        assert result.records_deactivated == 1

    def test_keep_stale_suppresses_the_prune(self):
        self._old_thread(999, days=30)

        run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}), keep_stale=True)

        assert HNThread.objects.filter(hn_id=999).exists()

    def test_a_thread_below_the_sweep_floor_is_removed(self):
        """The floor is the retention policy, not a rule consulted once at
        discovery -- otherwise a stored row could sit below the bar for a
        fortnight, and the counter that would explain the bank could not exist."""
        self._old_thread(999, days=1, points=2, num_comments=3)

        result = run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}))

        assert not HNThread.objects.filter(hn_id=999).exists()
        assert result.summary["threads_below_floor"] == 1

    def test_a_thread_above_the_sweep_floor_but_below_the_window_floor_stays(self):
        """The floor applied is the *sweep's*. That is what keeps raising the
        window floor -- a discovery decision -- from retroactively emptying the
        bank, while the sweep floor still holds stored rows to a real bar."""
        self._old_thread(998, days=1, points=40, num_comments=10)

        result = run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}))

        assert HNThread.objects.filter(hn_id=998).exists()
        assert result.summary["threads_below_floor"] == 0

    def test_a_thread_with_no_reported_comment_count_does_not_stay(self):
        """It cannot be shown to clear the floor, and SQL NULL comparisons are
        never true -- so `num_comments < floor` alone would silently keep it."""
        self._old_thread(997, days=1, points=500, num_comments=None)

        run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}))

        assert not HNThread.objects.filter(hn_id=997).exists()

    def test_the_prune_reports_its_two_reasons_separately(self):
        self._old_thread(996, days=30)
        self._old_thread(995, days=1, points=1, num_comments=1)

        result = run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}))

        assert result.summary["threads_pruned"] == 2
        assert result.summary["threads_below_floor"] == 1
        assert result.records_deactivated == 2

    def test_a_dry_run_rolls_back_a_floor_removal_too(self):
        self._old_thread(994, days=1, points=1, num_comments=1)

        result = run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}), dry_run=True)

        assert result.summary["threads_below_floor"] == 1
        assert HNThread.objects.filter(hn_id=994).exists()

    def test_the_sweep_floor_reaches_the_api(self):
        """Applied server-side, so trivia is never transferred in the first place."""
        client = FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)})
        cfg = discussions.hn_config()

        run(client)

        assert client.term_filters
        assert all(f == (cfg.sweep_min_points, cfg.sweep_min_comments) for f in client.term_filters)

    def test_a_dry_run_rolls_the_prune_back(self):
        """The whole point of `--dry-run` here: see what would be deleted, delete
        nothing."""
        self._old_thread(999, days=30)

        result = run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}), dry_run=True)

        assert result.summary["threads_pruned"] == 1
        assert HNThread.objects.filter(hn_id=999).exists()
        assert not HNThread.objects.filter(hn_id=11).exists()

    def test_a_dry_run_reports_real_counters(self):
        """It performs the whole pipeline and reports what it would have written."""
        result = run(
            FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11, children=[hn_comment(21)])}),
            dry_run=True,
        )

        assert result.summary["comments_stored"] == 1
        assert result.records_created >= 1

    def test_a_dry_run_does_not_make_the_data_look_fresh(self):
        """Same rule the model sources carry: a rehearsal is not a refresh."""
        run(
            FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}),
            dry_run=True,
        )

        assert not SyncRun.objects.filter(
            source=Source.HACKERNEWS.value, status=SyncStatus.SUCCESS.value, dry_run=False
        ).exists()


@pytest.mark.django_db
class TestLockingAndSkips:
    def test_a_held_lock_skips_rather_than_queuing(self):
        from leaderboard.locking import run_lock

        with run_lock(Source.HACKERNEWS.value):
            result = discussions.refresh_discussions(
                client=FakeHNClient(), use_lock=True, now=NOW, synced_at=NOW
            )

        assert result.status == SyncStatus.SKIPPED.value
        assert result.error_code == "already_running"

    def test_an_open_run_row_skips_the_second_run(self):
        """The database-level backstop, which holds even when Redis is gone."""
        SyncRun.objects.create(
            source=Source.HACKERNEWS.value,
            status=SyncStatus.RUNNING.value,
            started_at=NOW,
        )

        result = run(FakeHNClient(window_hits=[story(11, "LLM")]))

        assert result.status == SyncStatus.SKIPPED.value

    def test_a_stale_running_row_is_reaped(self):
        """Otherwise one SIGKILLed worker blocks every future run, permanently."""
        SyncRun.objects.create(
            source=Source.HACKERNEWS.value,
            status=SyncStatus.RUNNING.value,
            started_at=NOW - timedelta(hours=12),
        )

        result = run(FakeHNClient(window_hits=[story(11, "LLM")], items={11: tree(11)}))

        assert result.status == SyncStatus.SUCCESS.value

    def test_disabled_reports_a_skip_rather_than_a_failure(self):
        result = discussions.skip_disabled()

        assert result.status == SyncStatus.SKIPPED.value
        assert result.error_code == "disabled"


@pytest.mark.django_db
class TestManualPaths:
    def test_an_explicit_id_list_reads_the_item_endpoint_directly(self):
        """So a thread no search result mentions is still addressable."""
        client = FakeHNClient(items={555: tree(555, children=[hn_comment(556)])})

        result = run(client, hn_ids=[555], skip_discovery=True)

        assert result.status == SyncStatus.SUCCESS.value
        assert client.window_calls == []
        assert HNThread.objects.filter(hn_id=555).exists()

    def test_an_explicit_id_is_not_pruned_away_in_the_same_run(self):
        """`--hn-id` on an old story is a debugging request, so deleting the row
        moments after writing it would make the flag useless. A later scheduled run
        ages it out, so the bank still cannot grow without bound."""
        old = hn_item(777, title="An old thread", created_at_i=int(NOW.timestamp()) - 90 * 86400)

        run(FakeHNClient(items={777: old}), hn_ids=[777], skip_discovery=True)

        assert HNThread.objects.filter(hn_id=777).exists()

    def test_a_manual_id_is_admitted_even_without_a_keyword(self):
        """An operator naming a thread has already decided it belongs; silently
        dropping it because the title lacks a keyword would break the one tool for
        inspecting a specific story."""
        client = FakeHNClient(items={555: hn_item(555, title="Nothing relevant here")})

        run(client, hn_ids=[555], skip_discovery=True)

        thread = HNThread.objects.get(hn_id=555)
        assert thread.relevance_terms == []
        assert thread.source_metadata["discovered_by"] == ["manual"]

    def test_skip_discovery_refetches_the_standing_bank(self):
        run(FakeHNClient(window_hits=[story(11, "LLM", num_comments=6)], items={11: tree(11, children=[hn_comment(21)])}))

        client = FakeHNClient(items={11: tree(11, children=[hn_comment(21), hn_comment(22)])})
        result = run(client, skip_discovery=True)

        assert client.window_calls == []
        assert client.item_calls == [11]
        assert result.summary["stream"] == "refresh-only"

    def test_an_unfetchable_manual_id_is_counted_not_fatal(self):
        result = run(FakeHNClient(fail_items={555}), hn_ids=[555], skip_discovery=True)

        assert result.records_failed == 1

    def test_a_forced_refetch_works_through_the_whole_bank(self):
        """The property that makes `--skip-discovery` usable for applying a
        vocabulary change.

        Ranking the force path by `rank_score` -- as the hourly path legitimately
        does -- means every forced run fetches the *same* top `budget` rows and the
        tail is never reached. Ordering by `fetched_at` is what lets an operator
        get to the end of the bank, and this is the regression guard for it.

        Each pass is given a distinct `synced_at`, because `fetched_at` is the
        ordering signal -- with one fixed clock there would be no staleness to
        order by and the test would prove nothing.
        """
        hits = [story(100 + index, "LLM", points=1000 - index) for index in range(4)]
        items = {100 + index: tree(100 + index) for index in range(4)}
        # Seed the bank *and* its trees, so every thread starts fetched.
        run(FakeHNClient(window_hits=hits, items=items), max_trees=10)

        seen: list[int] = []
        for minute in (1, 2):
            at = NOW + timedelta(minutes=minute)
            client = FakeHNClient(items=items)
            run(client, skip_discovery=True, max_trees=2, synced_at=at, now=at)
            seen.extend(client.item_calls)

        # Two runs of two, and every thread fetched exactly once -- rather than
        # the top two twice and the bottom two never.
        assert sorted(seen) == [100, 101, 102, 103]

    def test_never_fetched_threads_go_first_when_forcing(self):
        """A thread with no `fetched_at` cannot be compared against a date, so it
        is given an epoch rather than raising -- and it sorts ahead of everything,
        which is the right priority: it has no tree at all."""
        hits = [story(100, "LLM", points=1000), story(101, "LLM", points=900)]
        items = {100: tree(100), 101: tree(101)}
        # A budget of one leaves the lower-ranked thread discovered but tree-less.
        run(FakeHNClient(window_hits=hits, items=items), max_trees=1)
        assert HNThread.objects.get(hn_id=100).fetched_at is not None
        assert HNThread.objects.get(hn_id=101).fetched_at is None

        at = NOW + timedelta(minutes=1)
        client = FakeHNClient(items=items)
        run(client, skip_discovery=True, max_trees=1, synced_at=at, now=at)

        assert client.item_calls == [101]

    def test_the_number_of_runs_to_cover_the_bank_is_bounded(self):
        """Stated as the operator's question rather than as an implementation
        detail: a bank of N with a budget of B is covered within ceil(N/B) forced
        runs.

        Five and two do not divide, so the third run necessarily revisits one
        thread after reaching the last un-fetched one. That is the honest shape of
        a sweep rather than a flaw -- what matters is that every thread is reached,
        which the alternative (always the top `budget` by rank) could never do.
        """
        hits = [story(200 + index, "LLM") for index in range(5)]
        items = {200 + index: tree(200 + index) for index in range(5)}
        run(FakeHNClient(window_hits=hits, items=items), max_trees=10)

        seen: list[int] = []
        for minute in (1, 2, 3):
            at = NOW + timedelta(minutes=minute)
            client = FakeHNClient(items=items)
            run(client, skip_discovery=True, max_trees=2, synced_at=at, now=at)
            seen.extend(client.item_calls)

        assert set(seen) == {200, 201, 202, 203, 204}
        assert len(seen) == 6
