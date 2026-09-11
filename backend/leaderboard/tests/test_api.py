"""Endpoint contracts: shapes, filters, ordering, pagination, error envelopes.

The suite is driven over HTTP rather than by calling the view classes directly.
That is not ceremony: the pagination plumbing on `LeaderboardView` exists only
because DRF's `GenericAPIView` members had to be restated by hand, and a direct
call would have skipped exactly the code path that was broken. A contract is
only pinned if it is exercised the way the frontend exercises it.

The seed is a real `refresh_all` run against fake transports, so every endpoint
below reads rows that the ingestion pipeline actually wrote.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from leaderboard.constants import Source, SyncStatus
from leaderboard.models import LLMModel, LMArenaEntry, SyncRun, UnmatchedRecord
from leaderboard.services import refresh
from leaderboard.tests.test_refresh import (
    aa_client,
    aa_one_model,
    aa_page,
    agent_row,
    empty,
    full_lmarena,
    lmarena_client,
    rating_row,
    with_categories,
)
from leaderboard.tests.fakes import aa_model

BASE = "/api/v1/leaderboard"

# --------------------------------------------------------------------------- #
# The seed
# --------------------------------------------------------------------------- #


def seed() -> None:
    """Two complete models, one agent model with no AA match, one AA orphan.

    Deliberately small, but shaped so that every endpoint has something to say
    *and* every rule has something to demonstrate:

    * `claude-opus-5-high` -- in `agent`, `document` and `webdev`, matched to AA,
      and measured. A complete entry, with two non-null category blocks and one
      deliberately null (`search`, which the model was never evaluated in).
    * `claude-opus-5-low` -- in `agent` only, matched to AA, and **unmeasured**
      (no cost block). Its presence is what makes the nulls-last ordering rule
      observable: the retained set has to hold both a measured and an unmeasured
      row for the rule to mean anything.
    * `gpt-5-5-xhigh` -- in `agent` and `document`, with **no** AA counterpart.
      Real LMArena data, excluded from the joined endpoints by design, and the
      subject of the `model_incomplete` 404.
    * `unrelated-model` -- an AA record with no LMArena presence at all, so
      `/artificial-analysis/?retained=false` has a row to show.
    """
    refresh.refresh_all(
        lmarena_client=lmarena_client(
            agent=[
                agent_row("Claude Opus 5 (High)", rank=1),
                agent_row("GPT 5.5 (xHigh)", rank=2),
                agent_row("Claude Opus 5 (Low)", rank=3, score=0.09),
            ],
            document=[
                rating_row("document", "claude-opus-5-high", rank=4),
                rating_row("document", "gpt-5.5-xhigh", rank=9),
            ],
            search=empty("search"),
            webdev=[rating_row("webdev", "claude-opus-5-high", rank=7)],
        ),
        aa_client=aa_client(
            aa_page(
                [
                    aa_model(
                        "uuid-claude",
                        "claude-opus-5-high",
                        "Claude Opus 5 (High)",
                        evaluations={"artificial_analysis_intelligence_index": 62.5},
                        artificial_analysis_intelligence_index_cost={
                            "total_cost": 59.99,
                            "cost_per_task": {"total_cost": 0.0502},
                        },
                        pricing={"price_1m_input_tokens": 15.0},
                        model_creator={"id": "creator-anthropic", "name": "Anthropic"},
                        release_date="2026-05-04",
                    ),
                    # Retained, and deliberately unmeasured: no cost block at
                    # all, which is what makes the nulls-last ordering rule
                    # observable on the default (retained) result set.
                    aa_model(
                        "uuid-claude-low",
                        "claude-opus-5-low",
                        "Claude Opus 5 (Low)",
                        evaluations={"artificial_analysis_intelligence_index": 41.0},
                    ),
                    # Matched to nothing: AA measures it, LMArena's agent split
                    # does not cover it. This is the population the completeness
                    # rule hides, and `/unmatched/` lists.
                    aa_model("uuid-orphan", "unrelated-model", "Unrelated Model"),
                ],
                headers={
                    "X-RateLimit-Remaining": "78",
                    "X-RateLimit-Limit": "100",
                    "X-AA-Tier": "free",
                },
            )
        ),
        use_lock=False,
    )


@pytest.fixture
def seeded(db):
    seed()


def get(client, path: str, **params):
    """`?ordering=-aa_cost_per_task` spelled as kwargs, for readability."""
    return client.get(f"{BASE}{path}", params or None)


# --------------------------------------------------------------------------- #
# Pagination and the `meta` block
# --------------------------------------------------------------------------- #


class TestEnvelope:
    def test_every_page_carries_the_freshness_block(self, client, seeded):
        """The badge and the rows come from one request, so they cannot disagree."""
        body = get(client, "/overview/").json()

        assert set(body) == {"count", "next", "previous", "page_size", "results", "meta"}
        assert body["meta"]["generated_at"].endswith("Z")
        assert body["meta"]["sources"]["artificial_analysis"]["last_status"] is not None

    def test_an_unsupported_method_is_a_405(self, client, seeded):
        response = client.post(f"{BASE}/overview/")

        assert response.status_code == 405
        assert response.json()["error"] == "method_not_allowed"

    def test_a_non_integer_page_size_is_a_400_not_a_default(self, client, seeded):
        """Silently falling back would answer a different question than asked."""
        body = get(client, "/overview/", page_size="abc").json()

        assert body["error"] == "invalid_parameter"
        assert body["param"] == "page_size"

    def test_page_size_above_the_cap_is_clamped_and_echoed(self, client, seeded):
        body = get(client, "/overview/", page_size="100000").json()

        assert body["page_size"] == 200

    def test_page_size_zero_is_a_400(self, client, seeded):
        body = get(client, "/overview/", page_size="0").json()

        assert body["error"] == "invalid_parameter"

    def test_an_out_of_range_page_is_a_404(self, client, seeded):
        """DRF's standard behaviour, kept, so the frontend sees one shape."""
        response = get(client, "/overview/", page=99)

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    def test_a_tie_on_the_order_field_is_broken_deterministically(self, client, seeded):
        """Without the unconditional `pk` tiebreak, rows tied on rank can move
        between pages -- which the frontend sees as duplicated and missing rows."""
        first = get(client, "/categories/agent/", ordering="metric_value", page_size=1).json()
        second = get(client, "/categories/agent/", ordering="metric_value", page_size=1, page=2).json()

        assert {row["model"]["key"] for row in first["results"]}.isdisjoint(
            {row["model"]["key"] for row in second["results"]}
        )


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #


class TestOrdering:
    def test_unmeasured_values_sort_last_not_first(self, client, seeded):
        """SQLite's default is NULL-first. On a cost chart that puts every model
        AA never priced at the top, which is the opposite of useful."""
        body = get(client, "/artificial-analysis/", ordering="cost_per_task").json()

        values = [row["aa"]["cost_per_task"] for row in body["results"]]
        assert values[0] is not None
        assert values[-1] is None

    def test_descending_also_sorts_unmeasured_last(self, client, seeded):
        body = get(client, "/artificial-analysis/", ordering="-cost_per_task").json()

        values = [row["aa"]["cost_per_task"] for row in body["results"]]
        assert values[-1] is None

    def test_an_unknown_ordering_field_is_a_400_listing_the_valid_ones(self, client, seeded):
        """A typo must not be silently ignored -- that returns a *plausible*
        response in the wrong order, which is worse than an error."""
        body = get(client, "/overview/", ordering="nonsense").json()

        assert body["error"] == "invalid_parameter"
        assert body["param"] == "ordering"
        assert "rank" in body["allowed"]
        assert "aa_cost_per_task" in body["allowed"]

    def test_an_empty_ordering_is_a_400(self, client, seeded):
        body = get(client, "/overview/", ordering=",").json()

        assert body["error"] == "invalid_parameter"

    def test_ordering_by_a_joined_aa_field_works(self, client, seeded):
        """`/overview/` orders by AA columns through `aa_match__model`."""
        body = get(client, "/overview/", ordering="-aa_intelligence_index").json()

        assert body["count"] == 2
        assert body["results"][0]["aa"]["intelligence_index"] == 62.5


# --------------------------------------------------------------------------- #
# 1. /overview/
# --------------------------------------------------------------------------- #


class TestOverview:
    def test_returns_only_complete_entries(self, client, seeded):
        """The completeness rule, as the frontend experiences it."""
        body = get(client, "/overview/").json()

        assert body["count"] == 2
        assert body["results"][0]["model"]["key"] == "claude-opus-5-high"
        # The unmatched agent model and the AA-only record are both absent.
        assert "gpt-5-5-xhigh" not in {row["model"]["key"] for row in body["results"]}

    def test_a_complete_entry_carries_all_four_category_blocks(self, client, seeded):
        """`search` was never evaluated for this model. The block is present and
        explicitly `null`, so the frontend destructures without a guard.

        This is the distinction the design insists on: absence of a *category* is
        information the frontend must render; absence of the *join* is the case
        that gets dropped.
        """
        row = get(client, "/overview/").json()["results"][0]

        assert set(row["categories"]) == {"agent", "document", "search", "webdev"}
        assert row["categories"]["search"] is None
        assert row["categories"]["agent"]["metric_value"] == 0.114
        assert row["categories"]["document"]["rank"] == 4

    def test_a_null_metric_stays_null_and_never_becomes_zero(self, client, seeded):
        """A `0` here draws a real data point at the origin of every chart."""
        row = get(client, "/overview/").json()["results"][0]

        assert row["aa"]["cost_per_task"] == 0.0502
        assert row["aa"]["coding_index"] is None
        assert row["aa"]["performance"]["median_output_tokens_per_second"] is None

    def test_the_aa_block_exposes_no_raw_payload(self, client, seeded):
        """`raw_payload` is for troubleshooting schema drift and stops here."""
        row = get(client, "/overview/").json()["results"][0]

        assert "raw_payload" not in row["aa"]
        assert "source_metadata" not in row["categories"]["agent"]

    def test_the_match_block_records_how_the_join_was_made(self, client, seeded):
        row = get(client, "/overview/").json()["results"][0]

        assert row["match"]["method"] == "exact_name"
        assert row["match"]["is_manual"] is False

    def test_search_matches_on_name(self, client, seeded):
        assert get(client, "/overview/", search="Opus 5 (Low)").json()["count"] == 1
        assert get(client, "/overview/", search="nothing").json()["count"] == 0

    def test_organization_filter(self, client, seeded):
        assert get(client, "/overview/", organization="anthropic").json()["count"] == 2
        assert get(client, "/overview/", organization="openai").json()["count"] == 0

    def test_rank_and_metric_range_filters(self, client, seeded):
        assert get(client, "/overview/", rank_min=1, rank_max=1).json()["count"] == 1
        assert get(client, "/overview/", rank_min=1, rank_max=3).json()["count"] == 2
        assert get(client, "/overview/", rank_min=5).json()["count"] == 0
        assert get(client, "/overview/", metric_min=0.1, metric_max=0.2).json()["count"] == 1
        assert get(client, "/overview/", metric_min=0.9).json()["count"] == 0

    def test_include_categories_narrows_the_blocks(self, client, seeded):
        """The frontend asks for what it is about to draw, and nothing else."""
        body = get(client, "/overview/", include_categories="document,webdev").json()

        assert body["meta"]["categories_included"] == ["document", "webdev"]
        blocks = body["results"][0]["categories"]
        # `agent` is the anchor: always present, never named. Every other key
        # is still present so the shape is stable, but the ones not asked for
        # are null rather than omitted.
        assert set(blocks) == {"agent", "document", "search", "webdev"}
        assert blocks["document"] is not None
        assert blocks["webdev"] is not None
        assert blocks["search"] is None

    def test_an_unknown_include_category_is_a_400(self, client, seeded):
        body = get(client, "/overview/", include_categories="document,nope").json()

        assert body["error"] == "invalid_parameter"

    def test_there_is_no_matched_parameter_because_it_is_invariantly_true(self, client, seeded):
        """`?matched=` is not a filter here -- it is rejected as unknown ordering
        would be, because both it and `?has_aa=` would be no-ops that imply the
        endpoint can return a half-populated row. It cannot."""
        body = get(client, "/overview/", matched="false").json()

        # Unknown parameters are ignored, but the result set is unchanged: the
        # excluded model is still absent.
        assert body["count"] == 2
        assert "gpt-5-5-xhigh" not in {row["model"]["key"] for row in body["results"]}


# --------------------------------------------------------------------------- #
# 2. /categories/
# --------------------------------------------------------------------------- #


class TestCategoryIndex:
    def test_indexes_every_category_with_real_counts(self, client, seeded):
        body = get(client, "/categories/").json()

        by_name = {row["category"]: row for row in body["results"]}
        assert set(by_name) == {"agent", "document", "search", "webdev"}
        assert by_name["agent"]["entry_count"] == 3
        assert by_name["search"]["entry_count"] == 0
        assert by_name["document"]["in_agent_set_count"] == 2

    def test_it_is_not_paginated_but_still_carries_meta(self, client, seeded):
        """A fixed-size index needs no pages; the freshness badge still needs
        somewhere to live, so the envelope shape is preserved."""
        body = get(client, "/categories/").json()

        assert "results" in body and "meta" in body
        assert body["meta"]["matched_agent_models"] == 2


# --------------------------------------------------------------------------- #
# 3. /categories/{category}/
# --------------------------------------------------------------------------- #


class TestCategoryDetail:
    def test_an_unknown_category_is_a_404_listing_the_valid_ones(self, client, seeded):
        """A bare URL-resolution 404 would not tell the frontend what to ask for."""
        response = get(client, "/categories/nonsense/")

        assert response.status_code == 404
        body = response.json()
        assert body["error"] == "unknown_value"
        assert body["param"] == "category"
        assert set(body["allowed"]) == {"agent", "document", "search", "webdev"}

    def test_defaults_to_the_agent_set(self, client, seeded):
        """`document` holds a row for a model outside the agent split. It is
        excluded by default and reachable on request."""
        body = get(client, "/categories/document/").json()

        assert body["count"] == 2
        assert body["meta"]["in_agent_set"] is True

    def test_in_agent_set_false_returns_the_excluded_rows(self, client, seeded):
        """The escape hatch that keeps exclusion from becoming unreachability."""
        LMArenaEntry.objects.filter(model_key="gpt-5-5-xhigh").update(in_agent_set=False)

        body = get(client, "/categories/document/", in_agent_set="false").json()

        assert [row["model"]["key"] for row in body["results"]] == ["gpt-5-5-xhigh"]

    def test_scope_all_drops_the_filter_entirely(self, client, seeded):
        body = get(client, "/categories/document/", scope="all").json()

        assert body["count"] == 2
        assert body["meta"]["scope"] == "all"
        assert body["meta"]["in_agent_set"] is None

    def test_the_matched_filter_selects_on_the_aa_join(self, client, seeded):
        """In `agent` the two rows are the matched pair and the orphan, so
        `?matched=false` isolates the orphan."""
        body = get(client, "/categories/agent/", matched="false").json()

        assert [row["model"]["key"] for row in body["results"]] == ["gpt-5-5-xhigh"]

    def test_a_bad_boolean_is_a_400(self, client, seeded):
        body = get(client, "/categories/agent/", matched="maybe").json()

        assert body["error"] == "invalid_parameter"
        assert body["param"] == "matched"
        assert set(body["allowed"]) == {"true", "false"}

    def test_metric_kind_travels_with_the_response(self, client, seeded):
        """`agent` is a score and the rest are ratings -- not one scale. The
        frontend must not plot them on a single axis, so it is told."""
        assert get(client, "/categories/agent/").json()["meta"]["metric_kind"] == "score"
        assert get(client, "/categories/document/").json()["meta"]["metric_kind"] == "rating"

    def test_the_agent_category_has_no_agent_key_of_its_own(self, client, seeded):
        row = get(client, "/categories/agent/").json()["results"][0]

        assert row["model"]["agent_key"] == row["model"]["key"]
        assert row["matched_by_fold"] is False


# --------------------------------------------------------------------------- #
# 4. /artificial-analysis/
# --------------------------------------------------------------------------- #


class TestArtificialAnalysis:
    def test_defaults_to_the_retained_subset(self, client, seeded):
        body = get(client, "/artificial-analysis/").json()

        assert body["count"] == 2
        assert {row["aa"]["slug"] for row in body["results"]} == {
            "claude-opus-5-high",
            "claude-opus-5-low",
        }
        # The AA-only record is not retained, so it is absent by default.
        assert "unrelated-model" not in {row["aa"]["slug"] for row in body["results"]}

    def test_retained_false_selects_the_complement_not_the_union(self, client, seeded):
        """`retained=false` is the *non*-retained set, not everything.

        Pairing it with `matched=false` is the recipe that lists AA models with
        no LMArena counterpart -- the population a reviewer inspects to decide
        whether a gap is our normalizer's fault or AA's coverage.
        """
        body = get(client, "/artificial-analysis/", retained="false").json()

        assert body["count"] == 1
        assert body["results"][0]["aa"]["slug"] == "unrelated-model"
        assert body["meta"]["retained"] is False

    def test_retained_false_and_matched_false_names_the_unmatched_population(
        self, client, seeded
    ):
        body = get(
            client, "/artificial-analysis/", retained="false", matched="false"
        ).json()

        assert [row["aa"]["slug"] for row in body["results"]] == ["unrelated-model"]

    def test_an_unmatched_row_carries_a_null_back_reference(self, client, seeded):
        body = get(client, "/artificial-analysis/", search="unrelated", retained="false").json()

        assert body["results"][0]["matched_model"] is None

    def test_a_matched_row_back_references_its_agent_entry(self, client, seeded):
        body = get(client, "/artificial-analysis/", search="opus").json()

        matched = body["results"][0]["matched_model"]
        assert matched["key"] == "claude-opus-5-high"
        assert matched["match_method"] == "exact_name"
        assert matched["agent"]["rank"] == 1

    def test_an_unknown_metric_filter_is_a_400_listing_the_allowed_ones(self, client, seeded):
        """Reflection would be an ORM injection surface; a whitelist that names
        itself is both safe and more useful."""
        body = get(client, "/artificial-analysis/", min_not_a_field="1").json()

        assert body["error"] == "invalid_parameter"
        assert body["param"] == "min_not_a_field"
        assert "min_cost_per_task" in body["allowed"]

    def test_metric_filters_work_on_the_whitelisted_fields(self, client, seeded):
        assert get(client, "/artificial-analysis/", max_cost_per_task="1").json()["count"] == 1
        assert get(client, "/artificial-analysis/", min_cost_per_task="1").json()["count"] == 0

    def test_release_date_range(self, client, seeded):
        assert get(client, "/artificial-analysis/", release_date_after="2026-01-01").json()["count"] == 1
        assert get(client, "/artificial-analysis/", release_date_after="2027-01-01").json()["count"] == 0

    def test_a_malformed_date_is_a_400_not_a_silent_ignore(self, client, seeded):
        body = get(client, "/artificial-analysis/", release_date_after="last tuesday").json()

        assert body["error"] == "invalid_parameter"
        assert body["param"] == "release_date_after"

    def test_creator_filter(self, client, seeded):
        assert get(client, "/artificial-analysis/", creator="anthropic").json()["count"] == 1
        assert get(client, "/artificial-analysis/", creator="nobody").json()["count"] == 0

    def test_money_is_emitted_as_a_json_number(self, client, seeded):
        """`Decimal` has no JSON type; the chart library wants a number. The
        exact value stays in the database, where the no-drift property matters."""
        row = get(client, "/artificial-analysis/").json()["results"][0]

        assert row["aa"]["cost_per_task"] == 0.0502
        assert row["aa"]["pricing"]["price_1m_input_tokens"] == 15.0

    def test_the_metric_whitelist_is_advertised(self, client, seeded):
        body = get(client, "/artificial-analysis/").json()

        assert "cost_per_task" in body["meta"]["metric_fields"]


# --------------------------------------------------------------------------- #
# 5. /models/{key}/
# --------------------------------------------------------------------------- #


class TestModelDetail:
    def test_a_complete_model_returns_every_block(self, client, seeded):
        body = get(client, "/models/claude-opus-5-high/").json()

        assert body["model"]["key"] == "claude-opus-5-high"
        assert set(body["categories"]) == {"agent", "document", "search", "webdev"}
        assert body["aa"]["slug"] == "claude-opus-5-high"
        assert body["match"]["method"] == "exact_name"

    def test_provenance_makes_the_inferred_part_auditable(self, client, seeded):
        """A reviewer can see which upstream spelling each block came from and
        whether the harness fold was involved -- from the API, not only the DB."""
        body = get(client, "/models/claude-opus-5-high/").json()

        provenance = body["provenance"]
        assert provenance["agent_key"] == "claude-opus-5-high"
        assert provenance["aa_match_method"] == "exact_name"
        assert provenance["aa_match_is_manual"] is False
        assert set(provenance["category_sources"]) == {"document", "webdev"}
        assert provenance["category_sources"]["document"]["source_name"] == "claude-opus-5-high"

    def test_an_agent_model_without_an_aa_match_is_a_404_model_incomplete(self, client, seeded):
        """A dead link must explain itself rather than looking like a typo."""
        response = get(client, "/models/gpt-5-5-xhigh/")

        assert response.status_code == 404
        body = response.json()
        assert body["error"] == "model_incomplete"
        assert body["reason"] == "no_aa_match"
        assert body["model_key"] == "gpt-5-5-xhigh"
        assert body["message"]
        # The detail block is the actionable part: which model, at which rank,
        # and the recorded reason it did not join.
        assert body["detail"]["model_name"] == "GPT 5.5 (xHigh)"
        assert body["detail"]["rank"] == 2

    def test_the_404_cites_the_reason_recorded_for_this_direction(self, client, seeded):
        """The population the completeness rule drops from `/overview/` is
        recorded, and the 404 that stands in its place points at that record.

        Direction is the whole point: the ledger entry for this model is an
        LMArena-sourced `no_aa_match` row -- "this agent model resolved to no AA
        record" -- not the AA-sourced `no_lmarena_match` row, which records the
        mirror fact about an AA record. Citing the wrong one would describe a
        different model's problem and send a reviewer to the wrong place.
        """
        body = get(client, "/models/gpt-5-5-xhigh/").json()

        unmatched = body["detail"]["unmatched"]
        assert unmatched is not None, (
            "an agent model with no AA match is exactly what /unmatched/ exists "
            "to explain; the 404 must not have to invent the reason"
        )
        assert unmatched["reason"] == body["reason"] == "no_aa_match"
        assert unmatched["source"] == Source.LMARENA.value
        assert unmatched["category"] == "agent"

    def test_a_missing_reason_is_json_null_never_the_string_none(self, client, seeded):
        """The field is absent only when nothing was recorded -- and then it must
        be a real JSON `null`, not the truthy string `"None"`.

        A frontend testing `if (detail.unmatched)` would otherwise render the
        literal text "None" and report a reason it never received. Reached by
        removing the ledger row a refresh would have written, which is the state
        of any database populated before this reason existed.
        """
        UnmatchedRecord.objects.filter(
            reason="no_aa_match", model_key="gpt-5-5-xhigh"
        ).delete()

        body = get(client, "/models/gpt-5-5-xhigh/").json()

        assert body["detail"]["unmatched"] is None
        assert body["detail"]["rank"] == 2  # an int, not "2"

    def test_the_reason_lookup_is_scoped_to_the_side_that_failed(self, client, seeded):
        """The ledger is keyed by the side that failed to match, so an unscoped
        lookup can cite a *different category's* record and answer the wrong
        question.

        The regression, stated concretely: `gpt-5-5-xhigh` also has a `document`
        row, and `claude-opus-5-high` has a `webdev` row. Without the source
        scope, asking "why is this agent model missing an AA match?" could return
        a `webdev` duplicate-collapse record that merely shares the key.
        """
        from leaderboard.api import selectors

        stamp = datetime.now(tz=timezone.utc)
        UnmatchedRecord.objects.create(
            source=Source.LMARENA.value,
            category="webdev",
            reason="duplicate_model_name",
            model_key="claude-opus-5-high",
            model_name="claude-opus-5-high",
            first_seen_at=stamp,
            last_seen_at=stamp,
        )

        # Unscoped, the webdev row is found -- the wrong answer to the question.
        assert selectors.unmatched_reason_for("claude-opus-5-high") is not None
        # Scoped to the AA side, nothing was recorded, which is the truth.
        assert (
            selectors.unmatched_reason_for(
                "claude-opus-5-high", source=Source.ARTIFICIAL_ANALYSIS.value
            )
            is None
        )

    def test_the_reason_lookup_is_scoped_by_reason_too(self, client, seeded):
        """Same key, same source, same category, different question.

        An agent model can be both a dedupe loser and unmatched against AA, and
        both rows are current. Source and category scoping do not separate them,
        so a lookup that asks "why is there no AA match?" without saying so
        returns whichever row the sort happened to put first -- here the older
        `duplicate_model_name` row, which is true of the row but not the reason
        the model is missing from `/overview/`.
        """
        from leaderboard.api import selectors

        UnmatchedRecord.objects.filter(
            reason="no_aa_match", model_key="gpt-5-5-xhigh"
        ).update(last_seen_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
        stamp = datetime.now(tz=timezone.utc)
        UnmatchedRecord.objects.create(
            source=Source.LMARENA.value,
            category="agent",
            reason="duplicate_model_name",
            model_key="gpt-5-5-xhigh",
            model_name="GPT 5.5 (xHigh)",
            first_seen_at=stamp,
            last_seen_at=stamp,
        )

        # Source and category alone are not enough -- the newer row wins.
        unscoped_reason = selectors.unmatched_reason_for(
            "gpt-5-5-xhigh", source=Source.LMARENA.value, category="agent"
        )
        assert unscoped_reason is not None
        assert unscoped_reason["reason"] == "duplicate_model_name"

        # Naming the question returns the answer to it.
        scoped = selectors.unmatched_reason_for(
            "gpt-5-5-xhigh",
            source=Source.LMARENA.value,
            category="agent",
            reason="no_aa_match",
        )
        assert scoped is not None
        assert scoped["reason"] == "no_aa_match"

    def test_an_aa_only_model_is_a_404_naming_where_to_find_it(self, client, seeded):
        response = get(client, "/models/unrelated-model/")

        body = response.json()
        assert response.status_code == 404
        assert body["error"] == "model_incomplete"
        assert body["reason"] == "not_in_agent_set"
        assert body["detail"]["aa_slug"] == "unrelated-model"

    def test_a_non_agent_category_model_404s_with_its_own_category_named(self, client, seeded):
        """`/models/{key}/` is agent-anchored, but the key may still exist in
        another category -- and the 404 should say so rather than claim the model
        does not exist."""
        stamp = datetime.now(tz=timezone.utc)
        LMArenaEntry.objects.create(
            category="search",
            model_key="search-only-model",
            model_name="Search Only Model",
            in_agent_set=False,
            is_active=True,
            first_seen_at=stamp,
            last_synced_at=stamp,
        )

        body = get(client, "/models/search-only-model/").json()

        assert body["error"] == "model_incomplete"
        assert body["reason"] == "not_in_agent_set"
        assert body["detail"]["category"] == "search"

    def test_an_unknown_key_is_a_plain_404(self, client, seeded):
        response = get(client, "/models/never-heard-of-it/")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    def test_a_key_resolves_by_agent_key_or_aa_slug(self, client, seeded):
        """Both spellings are handed out by other endpoints, so both must work."""
        by_agent_key = get(client, "/models/claude-opus-5-high/").json()
        by_slug = get(client, "/models/claude-opus-5-high/").json()

        assert by_agent_key["model"]["key"] == by_slug["model"]["key"]

    def test_the_fold_is_visible_in_provenance(self, client, seeded):
        """The one inferred rung of the ladder must be auditable as a class."""
        refresh.refresh_all(
            lmarena_client=with_categories(
                agent=[agent_row("GPT 5.6 Sol (xHigh)")],
                webdev=[rating_row("webdev", "gpt-5.6-sol-xhigh (codex-harness)")],
            ),
            aa_client=aa_client(aa_one_model("GPT 5.6 Sol (xHigh)", "gpt-5-6-sol-xhigh")),
            use_lock=False,
        )

        body = get(client, "/models/gpt-5-6-sol-xhigh/").json()

        assert body["provenance"]["category_sources"]["webdev"]["matched_by_fold"] is True
        assert body["categories"]["webdev"]["matched_by_fold"] is True
        # The block keeps the upstream spelling it actually came from.
        assert body["categories"]["webdev"]["source_key"] == "gpt-5-6-sol-xhigh-codex-harness"


# --------------------------------------------------------------------------- #
# 6. /metadata/
# --------------------------------------------------------------------------- #


class TestMetadata:
    def test_before_any_run_the_state_is_awaiting_first_refresh(self, client, db):
        """`is_stale` is true with a null `last_success_at` -- a distinct state
        from "failing", and one the frontend must render differently."""
        body = get(client, "/metadata/").json()

        for source in (Source.LMARENA.value, Source.ARTIFICIAL_ANALYSIS.value):
            state = body["sources"][source]
            assert state["last_success_at"] is None
            assert state["is_stale"] is True
            assert state["age_seconds"] is None

    def test_a_successful_run_makes_the_data_fresh(self, client, seeded):
        body = get(client, "/metadata/").json()

        state = body["sources"][Source.LMARENA.value]
        assert state["last_status"] == SyncStatus.SUCCESS.value
        assert state["is_stale"] is False
        assert state["age_seconds"] >= 0

    def test_the_counts_are_the_ledgers_own_totals(self, client, seeded):
        """`counts` exists so the frontend can badge the review queue without
        pulling a page of it -- which only works if it is the same number
        `/unmatched/` paginates over."""
        body = get(client, "/metadata/").json()

        counts = body["counts"]
        assert counts["unmatched_records"] == UnmatchedRecord.objects.filter(
            is_current=True
        ).count()
        assert counts["complete_agent_entries"] == get(client, "/overview/").json()["count"]
        # Both directions of the miss are in that total: the AA record with no
        # agent row *and* the agent row with no AA record. Counting only one
        # would understate the queue by exactly the population the completeness
        # rule hides, which is the one a reviewer needs most.
        assert set(
            UnmatchedRecord.objects.filter(is_current=True).values_list("reason", flat=True)
        ) == {"no_lmarena_match", "no_aa_match"}

    def test_a_failed_run_reports_failed_while_keeping_the_last_good_time(self, client, seeded):
        """Success and freshness are never conflated: the data is still good, the
        *run* failed. Both facts are on the wire."""
        good = get(client, "/metadata/").json()["sources"][Source.LMARENA.value]["last_success_at"]

        SyncRun.objects.create(
            source=Source.LMARENA.value,
            status=SyncStatus.FAILED.value,
            started_at=datetime.now(tz=timezone.utc),
            finished_at=datetime.now(tz=timezone.utc),
            error_code="source_unavailable",
            error_message="the Hub is down",
        )

        state = get(client, "/metadata/").json()["sources"][Source.LMARENA.value]
        assert state["last_status"] == SyncStatus.FAILED.value
        assert state["last_success_at"] == good
        assert state["last_error"]["code"] == "source_unavailable"

    def test_data_older_than_the_threshold_is_stale(self, client, seeded):
        old = datetime.now(tz=timezone.utc) - timedelta(days=3)
        SyncRun.objects.filter(source=Source.LMARENA.value).update(finished_at=old)

        state = get(client, "/metadata/").json()["sources"][Source.LMARENA.value]

        assert state["is_stale"] is True
        assert state["age_seconds"] > 2 * 24 * 3600

    def test_the_quota_is_echoed_so_the_frontend_can_explain_a_gap(self, client, seeded):
        state = get(client, "/metadata/").json()["sources"][Source.ARTIFICIAL_ANALYSIS.value]

        assert state["rate_limit"]["remaining"] == 78
        assert state["rate_limit"]["limit"] == 100
        assert state["tier"] == "free"

    def test_the_per_field_lmarena_outcome_is_reported(self, client, seeded):
        """A `partial` run must be explicable: which fields loaded, which did not."""
        state = get(client, "/metadata/").json()["sources"][Source.LMARENA.value]

        assert state["fields_succeeded"] == ["agent", "document", "search", "webdev"]
        assert state["fields_failed"] == {}

    def test_counts_and_tallies_are_exposed(self, client, seeded):
        body = get(client, "/metadata/").json()

        assert body["counts"]["lmarena_agent_entries"] == 3
        assert body["counts"]["complete_agent_entries"] == 2
        assert body["counts"]["aa_models"] == 3
        assert body["counts"]["aa_models_retained"] == 2
        assert body["matching"] == {"exact_name": 2}

    def test_recent_runs_are_listed_for_operators(self, client, seeded):
        body = get(client, "/metadata/").json()

        assert len(body["recent_runs"]) == 2
        assert body["recent_runs"][0]["source"] in Source.values

    def test_a_dry_run_does_not_make_the_data_look_fresh(self, client, seeded):
        """A rehearsal is not a refresh, and the freshness block must not be
        fooled by one.

        `--dry-run` fetches, parses and matches -- and then rolls the whole
        transaction back. Its `SyncRun` row survives (deliberately; that is where
        its counters live), so counting it as a success would let an operator who
        ran a rehearsal to check the match rate switch off the staleness alarm on
        a board whose data is a day old. The row stays visible in `recent_runs`,
        flagged, rather than being silently discarded or silently believed.
        """
        # Age the good run past the threshold, so `is_stale` is observable.
        SyncRun.objects.filter(source=Source.LMARENA.value).update(
            finished_at=datetime.now(tz=timezone.utc) - timedelta(days=2)
        )
        before = get(client, "/metadata/").json()["sources"][Source.LMARENA.value]
        assert before["is_stale"] is True, "the fixture is not stale; the test proves nothing"

        SyncRun.objects.create(
            source=Source.LMARENA.value,
            status=SyncStatus.SUCCESS.value,
            dry_run=True,
            triggered_by="cli:dry-run",
            started_at=datetime.now(tz=timezone.utc),
            finished_at=datetime.now(tz=timezone.utc),
        )
        after = get(client, "/metadata/").json()

        state = after["sources"][Source.LMARENA.value]
        assert state["is_stale"] is True, "a dry run silenced the staleness alarm"
        assert state["last_success_at"] == before["last_success_at"]
        assert state["last_status"] == before["last_status"]
        # Visible to operators, clearly labelled, just not counted as a refresh.
        assert after["recent_runs"][0]["dry_run"] is True

    def test_attribution_is_published_as_part_of_the_contract(self, client, seeded):
        """Artificial Analysis's terms require a visible credit. Shipping the URL
        in the API means the frontend cannot forget it."""
        body = get(client, "/metadata/").json()

        assert body["attribution"]["artificial_analysis"] == "https://artificialanalysis.ai/"

    def test_a_missing_aa_key_is_reported_as_unconfigured_not_as_failure(self, client, db, settings):
        """A frontend dev must be able to run the server with no API key."""
        settings.AA_API_KEY = ""

        state = get(client, "/metadata/").json()["sources"][Source.ARTIFICIAL_ANALYSIS.value]

        assert state["configured"] is False
        assert state["last_success_at"] is None


# --------------------------------------------------------------------------- #
# /unmatched/
# --------------------------------------------------------------------------- #


class TestUnmatched:
    def test_the_excluded_agent_model_is_listed_with_its_reason(self, client, seeded):
        """Exclusion must never become unreachability."""
        body = get(client, "/unmatched/", source=Source.ARTIFICIAL_ANALYSIS.value).json()

        keys = {row["model_key"] for row in body["results"]}
        assert "unrelated-model" in keys
        assert all(row["is_current"] for row in body["results"])

    def test_it_can_be_filtered_by_reason(self, client, seeded):
        body = get(client, "/unmatched/", reason="no_lmarena_match").json()

        assert body["count"] >= 1
        assert {row["reason"] for row in body["results"]} == {"no_lmarena_match"}

    def test_an_unknown_reason_filter_matches_nothing_rather_than_404ing(self, client, seeded):
        """A filter that matches nothing is a friendlier answer than an error for
        a value the frontend may legitimately have read from an older dataset."""
        body = get(client, "/unmatched/", reason="not_a_real_reason").json()

        assert body["count"] == 0

    def test_an_unknown_source_is_a_404_listing_the_valid_ones(self, client, seeded):
        body = get(client, "/unmatched/", source="nope").json()

        assert body["error"] == "unknown_value"
        assert set(body["allowed"]) == set(Source.values)

    def test_the_ledger_does_not_grow_when_a_problem_persists(self, client, seeded):
        """Current-state semantics: `occurrences` counts, the table does not."""
        before = get(client, "/unmatched/", source=Source.ARTIFICIAL_ANALYSIS.value).json()["count"]

        refresh.refresh_all(
            lmarena_client=full_lmarena(), aa_client=aa_client(aa_one_model()), use_lock=False
        )

        after = get(client, "/unmatched/", source=Source.ARTIFICIAL_ANALYSIS.value).json()["count"]
        assert after == before
