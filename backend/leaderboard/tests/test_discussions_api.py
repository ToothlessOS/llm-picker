"""Discussion endpoint contracts: shapes, filters, ordering, and the two traps.

The suite runs over HTTP rather than calling the view classes, for the reason
`test_api.py` gives: the pagination plumbing on `LeaderboardView` exists only
because DRF's `GenericAPIView` members had to be restated by hand, and a direct
call would skip exactly the path that was broken.

Two behaviours get disproportionate attention here, because both fail *quietly*:

* **`search` reaches through a join**, so a thread with twelve matching comments
  would be returned twelve times and `count` would report twelve. `test_..._counts_
  threads_not_comments` is the regression guard.
* **The provider filter rolls up**, so a thread tagged only `claude` must answer to
  `?entity=anthropic`. Without that the Provider dropdown looks empty.

The seed is written by the real `refresh_discussions` service through a fake
client, so these endpoints read rows the ingestion pipeline actually produced --
including the sanitized HTML, the `path` ordering and the tags.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
from leaderboard.tests.fakes import FakeHNClient, hn_comment, hn_item, hn_story_hit

BASE = "/api/v1/leaderboard"


def story(hn_id: int, title: str, **overrides) -> dict:
    """An LLM-related story posted an hour before the test's fixed instant.

    The timestamp is anchored to `_fixed_now()` rather than left at the shared
    fixture default, and that is load-bearing: the retention window is measured
    against `now`, so a story dated a year earlier would be pruned in the same
    transaction that stored it and every assertion below would see an empty bank.
    """
    overrides.setdefault("points", 300)
    # Above the bank's floor, or the prune would delete the thread in the same
    # transaction that stored it -- see the same note in
    # `test_discussions_refresh.story`.
    overrides.setdefault("num_comments", 10)
    overrides.setdefault("author", "poster")
    overrides.setdefault("created_at_i", int(_fixed_now().timestamp()) - 3600)
    return hn_story_hit(hn_id, title, **overrides)


def thread_tree(hn_id: int, *, children=None) -> dict:
    return hn_item(hn_id, title="Thread", children=children or [])


@pytest.fixture
def seeded(db):
    """One vendor, one service under it, and three threads.

    Written through the service rather than by hand so that the `path` values, the
    sanitized text and the tags are all produced by the code under test.
    """
    # The seeded vocabulary ships with migration 0009, and its contents are not
    # this file's business -- a change to it would silently change every count
    # below. Replaced with a vocabulary of exactly two entities.
    ProviderAlias.objects.all().delete()
    ProviderEntity.objects.all().delete()

    vendor = ProviderEntity.objects.create(
        slug="anthropic",
        label="Anthropic",
        kind=EntityKind.VENDOR,
        lmarena_organization="anthropic",
    )
    service = ProviderEntity.objects.create(
        slug="claude",
        label="Claude",
        kind=EntityKind.SERVICE,
        vendor=vendor,
    )
    ProviderAlias.objects.create(
        entity=vendor, alias_text="Anthropic", alias_key="anthropic", match_mode=MatchMode.WORD
    )
    ProviderAlias.objects.create(
        entity=service, alias_text="Claude", alias_key="claude", match_mode=MatchMode.TOKEN_PREFIX
    )

    client = FakeHNClient(
        window_hits=[
            story(1001, "Claude 5 is out", points=900, num_comments=10),
            story(1002, "A general LLM thread", points=500, num_comments=8),
            story(1003, "Anthropic ships a thing", points=100, num_comments=6),
        ],
        items={
            1001: thread_tree(
                1001,
                children=[
                    hn_comment(2001, author="alice", text="<p>I use Claude daily</p>"),
                    hn_comment(
                        2002,
                        author="bob",
                        text="<p>A reply with a zeppelin word</p>",
                        children=[],
                    ),
                ],
            ),
            1002: thread_tree(
                1002,
                children=[hn_comment(2010, author="carol", text="<p>Ollama is fine</p>")],
            ),
            1003: thread_tree(1003, children=[]),
        },
    )
    discussions.refresh_discussions(
        client=client, use_lock=False, synced_at=_fixed_now(), now=_fixed_now()
    )


def _fixed_now() -> datetime:
    """A fixed instant, so the date-range filter has a day to test against."""
    return datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def get(client, path: str, **params):
    return client.get(f"{BASE}{path}", params or None)


# --------------------------------------------------------------------------- #
# The list
# --------------------------------------------------------------------------- #


class TestDiscussionList:
    def test_returns_the_bank_newest_ranked_first(self, client, seeded):
        body = get(client, "/discussions/").json()

        assert body["count"] == 3
        assert [row["hn_id"] for row in body["results"]] == [1001, 1002, 1003]

    def test_defaults_to_the_top_ten_rather_than_fifty(self, client, seeded):
        """The draft asks for "the top 10", so the default page is ten."""
        body = get(client, "/discussions/").json()

        assert body["page_size"] == 10

    def test_a_row_carries_what_a_list_needs(self, client, seeded):
        row = get(client, "/discussions/").json()["results"][0]

        assert row["title"] == "Claude 5 is out"
        assert row["points"] == 900
        assert row["num_comments"] == 10
        assert row["comments_stored"] == 2
        assert row["tree_truncated"] is False
        assert row["hn_url"].endswith("id=1001")
        assert row["posted_at"].endswith("Z")

    def test_the_entity_chips_are_on_the_row(self, client, seeded):
        row = get(client, "/discussions/").json()["results"][0]

        assert [entity["slug"] for entity in row["entities"]] == ["claude"]

    def test_matched_comment_count_is_null_when_no_search_was_asked(self, client, seeded):
        """Present-and-null rather than absent, so its absence never has to be
        distinguished from "no matches"."""
        row = get(client, "/discussions/").json()["results"][0]

        assert "matched_comment_count" in row
        assert row["matched_comment_count"] is None

    def test_every_response_carries_the_freshness_block(self, client, seeded):
        meta = get(client, "/discussions/").json()["meta"]

        assert meta["sources"] is not None
        assert "discussions" in meta
        assert meta["discussions"]["counts"]["threads"] == 3
        assert meta["discussions"]["window_days"] == 14
        assert meta["discussions"]["is_stale"] is False

    def test_hacker_news_is_not_reported_as_a_model_source(self, client, seeded):
        """`meta.sources` describes the model rows a response carries and is typed
        on the frontend as exactly two sources. Adding a third would put
        discussion freshness on `/overview/`."""
        keys = set(get(client, "/discussions/").json()["meta"]["sources"])

        assert keys == {Source.LMARENA.value, Source.ARTIFICIAL_ANALYSIS.value}

    def test_an_empty_bank_is_an_empty_list_not_an_error(self, client, db):
        body = get(client, "/discussions/").json()

        assert body["count"] == 0
        assert body["results"] == []


# --------------------------------------------------------------------------- #
# Search -- the join trap
# --------------------------------------------------------------------------- #


class TestSearch:
    def test_matches_a_title(self, client, seeded):
        body = get(client, "/discussions/", search="Anthropic").json()

        assert [row["hn_id"] for row in body["results"]] == [1003]

    def test_matches_comment_text(self, client, seeded):
        body = get(client, "/discussions/", search="zeppelin").json()

        assert [row["hn_id"] for row in body["results"]] == [1001]

    def test_counts_threads_not_comments(self, client, seeded):
        """The regression that matters.

        `search` reaches through the comment relation, so without `distinct` a
        thread with two matching comments is returned -- and counted -- twice.
        """
        body = get(client, "/discussions/", search="Claude").json()

        # Thread 1001's title and its first comment both match.
        assert body["count"] == 1
        assert len(body["results"]) == 1

    def test_reports_how_many_comments_matched(self, client, seeded):
        row = get(client, "/discussions/", search="Claude").json()["results"][0]

        assert row["matched_comment_count"] == 1

    def test_a_search_matching_nothing_returns_nothing(self, client, seeded):
        body = get(client, "/discussions/", search="no-such-token").json()

        assert body["count"] == 0


# --------------------------------------------------------------------------- #
# The provider and service filter
# --------------------------------------------------------------------------- #


class TestEntityFilter:
    def test_filters_by_an_entity_slug(self, client, seeded):
        body = get(client, "/discussions/", entity="claude").json()

        assert [row["hn_id"] for row in body["results"]] == [1001]

    def test_a_vendor_filter_rolls_up_its_services(self, client, seeded):
        """The property the Provider dropdown depends on: a thread that only ever
        says "Claude" is still an Anthropic thread."""
        body = get(client, "/discussions/", entity="anthropic").json()

        assert sorted(row["hn_id"] for row in body["results"]) == [1001, 1003]

    def test_an_unknown_entity_is_a_400_listing_the_vocabulary(self, client, seeded):
        response = get(client, "/discussions/", entity="nope")

        assert response.status_code == 400
        body = response.json()
        assert body["error"] == "invalid_parameter"
        assert body["param"] == "entity"
        assert sorted(body["allowed"]) == ["anthropic", "claude"]

    def test_filters_by_kind(self, client, seeded):
        """`kind` is deliberately **not** rolled up, unlike `entity`.

        It answers "what kind of thing is the tag that fired", which is a question
        about the row -- so `kind=vendor` finds the thread whose title names a
        vendor, not the one that only names its service. Making both roll up would
        leave no way to ask the narrower question.
        """
        assert get(client, "/discussions/", kind="service").json()["count"] == 1
        assert get(client, "/discussions/", kind="vendor").json()["count"] == 1

    def test_an_unknown_kind_is_a_400(self, client, seeded):
        response = get(client, "/discussions/", kind="widget")

        assert response.status_code == 400
        assert sorted(response.json()["allowed"]) == ["service", "vendor"]

    def test_the_roll_up_is_one_condition_not_two(self, client, seeded):
        """Chaining two `filter()` calls would demand a single tag satisfying both
        branches, which no row can -- so `kind=service&entity=anthropic` must still
        find the Claude thread through its vendor."""
        body = get(client, "/discussions/", entity="anthropic", kind="service").json()

        assert [row["hn_id"] for row in body["results"]] == [1001]


# --------------------------------------------------------------------------- #
# Ordering, pagination, and the numeric filters
# --------------------------------------------------------------------------- #


class TestOrderingAndPaging:
    def test_orders_by_points(self, client, seeded):
        body = get(client, "/discussions/", ordering="points").json()

        assert [row["hn_id"] for row in body["results"]] == [1003, 1002, 1001]

    def test_an_unknown_ordering_key_is_a_400_listing_the_whitelist(self, client, seeded):
        response = get(client, "/discussions/", ordering="nope")

        assert response.status_code == 400
        body = response.json()
        assert body["error"] == "invalid_parameter"
        assert "rank_score" in body["allowed"]

    def test_nulls_sort_last(self, client, seeded):
        """`points` is nullable, and SQLite's default would float every unreported
        row to the top of the list."""
        HNThread.objects.filter(hn_id=1002).update(points=None)

        body = get(client, "/discussions/", ordering="points").json()

        assert body["results"][-1]["hn_id"] == 1002

    def test_pages_through_the_whole_bank(self, client, seeded):
        body = get(client, "/discussions/", page_size=2).json()

        assert body["count"] == 3
        assert len(body["results"]) == 2
        assert body["next"] is not None

    def test_a_page_size_over_the_cap_is_clamped_and_echoed_back(self, client, seeded):
        body = get(client, "/discussions/", page_size=9999).json()

        assert body["page_size"] == 200

    def test_a_non_integer_page_size_is_a_400(self, client, seeded):
        assert get(client, "/discussions/", page_size="abc").status_code == 400

    def test_a_page_out_of_range_is_a_404(self, client, seeded):
        assert get(client, "/discussions/", page=99).status_code == 404

    def test_filters_by_a_points_floor(self, client, seeded):
        body = get(client, "/discussions/", min_points=600).json()

        assert [row["hn_id"] for row in body["results"]] == [1001]

    def test_a_negative_floor_is_a_400(self, client, seeded):
        assert get(client, "/discussions/", min_points=-1).status_code == 400

    def test_filters_by_a_date_range_inclusively(self, client, seeded):
        """`posted_before` has to mean the *end* of that day, or a single-day
        filter would exclude everything after midnight."""
        day = _fixed_now().date().isoformat()

        body = get(client, "/discussions/", posted_after=day, posted_before=day).json()

        assert body["count"] == 3

    def test_a_malformed_date_is_a_400(self, client, seeded):
        response = get(client, "/discussions/", posted_after="last-tuesday")

        assert response.status_code == 400
        assert response.json()["param"] == "posted_after"

    def test_the_relevance_terms_are_readable_but_not_filterable(self, client, seeded):
        """The terms that put a thread in the bank are exposed so a reader can see
        *why* it is there, rather than only that it is.

        They are served, not filtered on: `relevance_terms` is a `JSONField`, and
        Django's `contains` lookup is unsupported on SQLite, so a filter would need
        a join table. That is more machinery than a filter nobody asked for earns,
        and a substring match over serialized JSON would be exactly the kind of
        thing that works until it does not.
        """
        row = get(client, "/discussions/").json()["results"][0]

        assert row["keywords"] == ["claude"]

    def test_an_unknown_keyword_parameter_is_ignored_rather_than_400(self, client, seeded):
        """No whitelist exists for it, so it is simply not read -- and, importantly,
        not silently *filtered* on either."""
        body = get(client, "/discussions/", keyword="nonsense").json()

        assert body["count"] == 3

    def test_a_non_get_is_rejected(self, client, seeded):
        assert client.post(f"{BASE}/discussions/").status_code == 405

    def test_the_serializer_does_not_leak_the_raw_payload(self, client, seeded):
        row = get(client, "/discussions/").json()["results"][0]

        assert "raw_payload" not in row
        assert "source_metadata" not in row


# --------------------------------------------------------------------------- #
# The detail
# --------------------------------------------------------------------------- #


class TestDiscussionDetail:
    def test_returns_the_thread_and_its_comments(self, client, seeded):
        body = get(client, "/discussions/1001/").json()

        assert body["thread"]["hn_id"] == 1001
        assert body["thread"]["title"] == "Claude 5 is out"
        assert len(body["comments"]) == 2

    def test_comments_come_back_as_a_flat_list_in_reading_order(self, client, seeded):
        """Ordered by `path`, so a comment is followed by its replies and then the
        next sibling -- pre-order, from a plain string sort."""
        comments = get(client, "/discussions/1001/").json()["comments"]

        assert [comment["hn_id"] for comment in comments] == [2001, 2002]
        assert [comment["path"] for comment in comments] == ["000000", "000001"]

    def test_every_node_carries_what_a_tree_needs(self, client, seeded):
        comment = get(client, "/discussions/1001/").json()["comments"][0]

        assert comment["depth"] == 0
        assert comment["parent_hn_id"] is None
        assert comment["sibling_index"] == 0
        assert comment["children_count"] == 0
        assert comment["hn_url"].endswith("id=2001")

    def test_html_is_served_pre_sanitized(self, client, seeded):
        """The sanitizer ran at ingest; the API ships its result verbatim because a
        second pass would be a second thing to keep correct."""
        comment = get(client, "/discussions/1001/").json()["comments"][0]

        assert comment["text_html"] == "<p>I use Claude daily</p>"
        assert comment["text_plain"] == "I use Claude daily"

    def test_a_comment_carries_the_alias_that_tagged_it(self, client, seeded):
        comment = get(client, "/discussions/1001/").json()["comments"][0]

        assert [entity["slug"] for entity in comment["entities"]] == ["claude"]
        assert comment["entities"][0]["matched_text"] == "Claude"
        assert comment["entities"][0]["vendor"] == "anthropic"

    def test_a_nested_reply_reports_its_depth_and_parent(self, client, seeded):
        HNComment.objects.filter(thread__hn_id=1001, hn_id=2002).update(
            hn_id=2002, parent_hn_id=2001, depth=1, path="000000.000000"
        )

        comment = get(client, "/discussions/1001/").json()["comments"][1]

        assert comment["depth"] == 1
        assert comment["parent_hn_id"] == 2001

    def test_max_depth_trims_the_tree(self, client, seeded):
        HNComment.objects.filter(thread__hn_id=1001, hn_id=2002).update(
            depth=3, path="000000.000000.000000.000000"
        )

        body = get(client, "/discussions/1001/", max_depth=1).json()

        assert [comment["hn_id"] for comment in body["comments"]] == [2001]
        assert body["meta"]["max_depth"] == 1

    def test_max_depth_above_the_ceiling_is_a_400(self, client, seeded):
        assert get(client, "/discussions/1001/", max_depth=9999).status_code == 400

    def test_search_restricts_the_comments(self, client, seeded):
        body = get(client, "/discussions/1001/", search="zeppelin").json()

        assert [comment["hn_id"] for comment in body["comments"]] == [2002]

    def test_entity_restricts_the_comments(self, client, seeded):
        body = get(client, "/discussions/1001/", entity="claude").json()

        assert [comment["hn_id"] for comment in body["comments"]] == [2001]

    def test_an_unknown_entity_is_a_400(self, client, seeded):
        assert get(client, "/discussions/1001/", entity="nope").status_code == 400

    def test_a_missing_thread_explains_itself(self, client, seeded):
        """A 404 that says why, and names the likely cause: threads age out."""
        response = get(client, "/discussions/424242/")

        assert response.status_code == 404
        body = response.json()
        assert body["error"] == "not_found"
        assert body["hn_id"] == 424242
        assert "14 days" in body["message"]

    def test_a_non_numeric_id_is_a_404_not_a_500(self, client, seeded):
        response = get(client, "/discussions/not-an-id/")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    def test_the_detail_carries_the_freshness_block(self, client, seeded):
        meta = get(client, "/discussions/1001/").json()["meta"]

        assert "discussions" in meta
        assert meta["comments_returned"] == 2


# --------------------------------------------------------------------------- #
# The entity index
# --------------------------------------------------------------------------- #


class TestEntityIndex:
    def test_lists_the_vocabulary_unpaginated(self, client, seeded):
        """Ordered by kind then label, which puts services before vendors --
        alphabetical on the kind value, not on any notion of importance. The tests
        below look rows up by slug rather than by position, so that ordering stays
        free to change."""
        body = get(client, "/discussions/entities/").json()

        assert sorted(row["slug"] for row in body["results"]) == ["anthropic", "claude"]

    def test_a_row_carries_what_a_dropdown_needs(self, client, seeded):
        rows = {
            row["slug"]: row
            for row in get(client, "/discussions/entities/").json()["results"]
        }

        assert rows["anthropic"]["label"] == "Anthropic"
        assert rows["anthropic"]["kind"] == "vendor"
        assert rows["anthropic"]["vendor"] is None
        assert rows["anthropic"]["lmarena_organization"] == "anthropic"
        assert rows["anthropic"]["aliases"] == ["Anthropic"]

    def test_a_service_names_its_vendor(self, client, seeded):
        rows = {row["slug"]: row for row in get(client, "/discussions/entities/").json()["results"]}

        assert rows["claude"]["vendor"] == "anthropic"

    def test_thread_count_is_the_direct_count_not_the_roll_up(self, client, seeded):
        """The number has to agree with the rows a click produces, and a click
        produces the *roll-up* -- so reporting a rolled-up total here would make
        the two disagree in the other direction. The vendor's direct count is the
        thread whose title names Anthropic."""
        rows = {row["slug"]: row for row in get(client, "/discussions/entities/").json()["results"]}

        assert rows["anthropic"]["thread_count"] == 1
        assert rows["claude"]["thread_count"] == 1

    def test_the_kinds_are_declared_for_the_ui(self, client, seeded):
        assert get(client, "/discussions/entities/").json()["meta"]["kinds"] == [
            "vendor",
            "service",
        ]

    def test_an_inactive_entity_is_not_offered(self, client, seeded):
        """A withdrawn entity must not appear in the dropdown, or a client would
        offer a filter that returns nothing."""
        ProviderEntity.objects.filter(slug="claude").update(is_active=False)

        slugs = [row["slug"] for row in get(client, "/discussions/entities/").json()["results"]]

        assert slugs == ["anthropic"]

    def test_an_inactive_entity_is_not_an_allowed_filter_value(self, client, seeded):
        ProviderEntity.objects.filter(slug="claude").update(is_active=False)

        response = get(client, "/discussions/", entity="claude")

        assert response.status_code == 400
        assert response.json()["allowed"] == ["anthropic"]


# --------------------------------------------------------------------------- #
# Freshness states
# --------------------------------------------------------------------------- #


class TestFreshness:
    def test_a_never_refreshed_bank_reports_awaiting_first_refresh(self, client, db):
        block = get(client, "/discussions/").json()["meta"]["discussions"]

        assert block["last_success_at"] is None
        assert block["is_stale"] is True

    def test_a_failed_run_keeps_the_last_good_success(self, client, seeded):
        """The contract every other source carries: success and freshness are never
        conflated, so the data you are serving is still good even though the *run*
        failed."""
        SyncRun.objects.create(
            source=Source.HACKERNEWS.value,
            status=SyncStatus.FAILED.value,
            started_at=_fixed_now() + timedelta(hours=1),
            finished_at=_fixed_now() + timedelta(hours=1),
            error_code="empty_response",
            error_message="no stories",
        )

        block = get(client, "/discussions/").json()["meta"]["discussions"]

        assert block["last_status"] == SyncStatus.FAILED.value
        assert block["last_error"]["code"] == "empty_response"
        assert block["last_success_at"] is not None
        assert block["is_stale"] is False

    def test_a_stale_bank_says_so(self, client, seeded):
        HNThread.objects.all().update(
            last_synced_at=_fixed_now() - timedelta(days=2)
        )
        SyncRun.objects.filter(source=Source.HACKERNEWS.value).update(
            finished_at=_fixed_now() - timedelta(days=2)
        )

        block = get(client, "/discussions/").json()["meta"]["discussions"]

        assert block["is_stale"] is True
        assert block["stale_after_seconds"] == 7200


# --------------------------------------------------------------------------- #
# The structural guarantees
# --------------------------------------------------------------------------- #


class TestStructural:
    def test_the_read_path_imports_no_client_matcher_or_service(self):
        """The guarantee the whole read path rests on, asserted directly on the
        three new modules.

        Behavioural tests can only prove the calls that *would have* happened along
        the paths they exercise. This closes the category: a future
        `from ..clients.hackernews import ...` or a selector that reaches for the
        service layer fails here at review time rather than on an unlucky branch.
        """
        from leaderboard.api import (
            discussion_selectors,
            discussion_serializers,
            discussion_views,
        )

        forbidden = (
            "clients.hackernews",
            "clients.http",
            "services.discussions",
            "services.refresh",
            "hn_matching",
            "hn_text",
            "locking",
        )
        for module in (discussion_views, discussion_selectors, discussion_serializers):
            with open(module.__file__) as handle:
                source = handle.read()
            for needle in forbidden:
                assert needle not in source, (
                    f"{module.__name__} references {needle!r}; the read path must "
                    "not be one import away from an external call"
                )

    def test_a_tag_is_a_stored_row_not_an_inference(self, client, seeded):
        """Matching ran at ingest, so the API's filter is a join. Withdrawing the
        alias changes nothing about what the API returns until the next refresh --
        which is the project's standing rule for derived data."""
        ProviderAlias.objects.all().delete()

        assert get(client, "/discussions/", entity="claude").json()["count"] == 1

    def test_tags_are_read_from_the_table_the_ingest_wrote(self, client, seeded):
        assert DiscussionTag.objects.exists()
        assert get(client, "/discussions/entities/").json()["results"]
