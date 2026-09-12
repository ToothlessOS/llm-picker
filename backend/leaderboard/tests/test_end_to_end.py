"""The whole pipeline, in the order production runs it.

Every other module tests one layer against its own seams. This one injects
nothing but the two external clients and asserts at the far end: fake pages in,
HTTP responses out. It exists to catch the class of bug no single-layer test can
-- a layer that is correct on its own terms while the *chain* is wrong, because
the seam between two layers disagrees about a name, a unit or a null.

The failure case is why this module matters most. A refresh that fails is the
normal state of an integration like this: keys expire, quotas empty, the Hub goes
down. What the frontend does at that moment is decided entirely by which stored
values change -- and the answer must be *none of them*. So the test does not
check that the endpoints merely still answer; it checks that every row is
byte-identical to the previous refresh's, while `meta` separately reports that
the attempt failed.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from leaderboard.clients.artificial_analysis import ArtificialAnalysisClient
from leaderboard.clients.exceptions import TransportError
from leaderboard.clients.http import RetryPolicy
from leaderboard.constants import Source, SyncStatus
from leaderboard.models import LMArenaEntry, ModelAlias
from leaderboard.services import refresh
from leaderboard.tests.fakes import FakeTransport, SleepRecorder, upper_bound_uniform
from leaderboard.tests.test_api import BASE, seed

# --------------------------------------------------------------------------- #
# The surfaces under comparison
# --------------------------------------------------------------------------- #

#: Endpoints that answer 200 with rows.
DATA_ENDPOINTS = (
    "/overview/",
    "/categories/",
    "/categories/agent/",
    "/categories/document/",
    "/categories/search/",
    "/categories/webdev/",
    "/artificial-analysis/",
    "/artificial-analysis/?retained=false",
    "/artificial-analysis/?retained=false&matched=false",
    "/models/claude-opus-5-high/",
    "/models/claude-opus-5-low/",
    "/unmatched/",
)

#: Endpoints whose *answer* is a 404. They belong in the comparison as much as
#: the 200s: `model_incomplete` is the most fragile payload in the API -- a
#: nested object whose numeric and null leaves are exactly what DRF's
#: `force_str` coercion used to corrupt -- and a 404 silently becoming a 200 is
#: the difference between "excluded, here is why" and "does not exist".
INCOMPLETE_ENDPOINTS = (
    "/models/gpt-5-5-xhigh/",
    "/models/unrelated-model/",
)

ALL_ENDPOINTS = DATA_ENDPOINTS + INCOMPLETE_ENDPOINTS

#: `/metadata/` is deliberately excluded from the byte-comparisons: its whole job
#: after a failed refresh is to report that the attempt happened, so it is
#: asserted on its own terms in `TestAFailedRefresh`.

#: Fields that record *that a refresh happened*, as opposed to anything it
#: measured. Only these may move when the same upstream data is ingested twice.
BOOKKEEPING_KEYS = frozenset(
    {
        # Computed from the clock while building the response.
        "generated_at",
        "age_seconds",
        # Run timestamps: a refresh really did happen, and these say when.
        "last_attempt_at",
        "last_success_at",
        "last_synced_at",
        "lmarena_last_synced_at",
        # The match was rebuilt; the ledger saw the same problem again.
        "last_matched_at",
        "last_seen_at",
        "occurrences",
    }
)

#: The subset of the above that moves on *any* request, even one that performs
#: no refresh at all. Used where the point is that nothing else moved.
REQUEST_CLOCK_KEYS = frozenset({"generated_at", "age_seconds"})


def snapshot(client) -> dict[str, tuple[int, Any]]:
    """Status and decoded body for every endpoint, as the frontend sees it.

    The status code travels with the body because a quarter of these endpoints
    answer with a deliberate 404.
    """
    return {
        path: (response.status_code, response.json())
        for path in ALL_ENDPOINTS
        for response in (client.get(f"{BASE}{path}"),)
    }


def scrub(value: Any, keys: frozenset[str] = BOOKKEEPING_KEYS) -> Any:
    """Drop the given keys from a decoded body, recursively."""
    if isinstance(value, dict):
        return {key: scrub(item, keys) for key, item in value.items() if key not in keys}
    if isinstance(value, list):
        return [scrub(item, keys) for item in value]
    return value


def scrub_snapshot(
    body: dict[str, tuple[int, Any]], keys: frozenset[str] = BOOKKEEPING_KEYS
) -> dict[str, tuple[int, Any]]:
    """Scrub every endpoint's payload, leaving the status codes alone.

    A separate helper rather than a `tuple` case inside `scrub`, because `scrub`
    walks *decoded JSON* where tuples do not exist; teaching it about them would
    make it tolerant of a shape the API cannot produce. The distinction is not
    academic: an earlier version passed the snapshot straight to `scrub`, which
    left every payload untouched and made the comparison fail on `generated_at`
    -- a false alarm, but one that would have been just as easy to miss in the
    other direction.
    """
    return {path: (status, scrub(payload, keys)) for path, (status, payload) in body.items()}


def differing_paths(before: Any, after: Any, prefix: str = "") -> set[str]:
    """Dotted paths at which two decoded bodies disagree.

    The scrub-and-compare assertions below are only as strong as their key list:
    an over-broad one would turn them into a no-op. This is the counterweight --
    the *raw* bodies are compared too, and must differ in nothing outside the
    keys the test names. It is also exercised directly, at the bottom of this
    module, because a comparator that always returned an empty set would make
    every "nothing changed" assertion here pass while the data changed entirely.
    """
    if isinstance(before, dict) and isinstance(after, dict):
        paths: set[str] = set()
        for key in set(before) | set(after):
            if key not in before or key not in after:
                paths.add(f"{prefix}{key}")
            else:
                paths |= differing_paths(before[key], after[key], f"{prefix}{key}.")
        return paths
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        paths = set()
        for index, (left, right) in enumerate(zip(before, after)):
            paths |= differing_paths(left, right, f"{prefix}{index}.")
        return paths
    return set() if before == after else {prefix.rstrip(".")}


def dead_aa_client() -> ArtificialAnalysisClient:
    """An AA client whose transport can never succeed.

    The transport is injected, so this exercises *our* retry loop rather than a
    library's interception: two attempts, two `TransportError`s, then the page's
    retry budget is exhausted and the run fails permanently.

    It raises `TransportError` -- not a bare `ConnectionError` -- because that is
    the contract `RequestsTransport` upholds: every `requests.RequestException`
    becomes a `TransportError` at the seam, and the client's retry loop catches
    nothing else. A fake raising anything else would escape the loop and
    exercise a code path production cannot reach.
    """
    return ArtificialAnalysisClient(
        "test-key",
        transport=FakeTransport(
            lambda index: TransportError(
                "upstream is unreachable", detail={"attempt": index + 1}
            )
        ),
        sleep=SleepRecorder(),
        uniform=upper_bound_uniform,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.01, max_delay=0.02),
    )


# --------------------------------------------------------------------------- #
# The pipeline answers, end to end
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestTheWholePipeline:
    def test_every_endpoint_answers_from_stored_data(self, client):
        """One run of the real pipeline, then every surface read over HTTP."""
        seed()

        body = snapshot(client)

        for path in DATA_ENDPOINTS:
            status, payload = body[path]
            assert status == 200, f"{path} -> {status}"
            assert payload, f"{path} answered with an empty body"

        for path in INCOMPLETE_ENDPOINTS:
            status, payload = body[path]
            assert status == 404, f"{path} -> {status}"
            assert payload["error"] == "model_incomplete"

    def test_the_joined_row_carries_both_sources(self, client):
        """The value the frontend actually plots: a rank from one source and an
        index from the other, joined by the pipeline rather than by the client."""
        seed()

        row = next(
            item
            for item in client.get(f"{BASE}/overview/").json()["results"]
            if item["model"]["key"] == "claude-opus-5-high"
        )

        assert row["categories"]["agent"]["rank"] == 1
        assert row["categories"]["agent"]["metric_kind"] == "score"
        assert row["aa"]["intelligence_index"] == 62.5
        assert row["aa"]["cost_per_task"] == 0.0502
        assert row["match"]["method"] == "exact_name"
        assert row["match"]["is_manual"] is False

    def test_a_re_run_of_unchanged_data_moves_only_the_bookkeeping(self, client):
        """Idempotency stated at the API surface rather than at row counters.

        Row counts can stay flat while a response quietly changes shape -- a
        re-normalized key, a rebuilt join, a deactivated row. Comparing the
        decoded bodies catches all of it, and the raw comparison keeps the
        scrubber honest by naming exactly what moved.
        """
        seed()
        before = snapshot(client)

        seed()
        after = snapshot(client)

        moved = {
            path: sorted(differing_paths(before[path][1], after[path][1]))
            for path in ALL_ENDPOINTS
        }
        strays = {
            path: paths
            for path, paths in moved.items()
            if any(leaf.split(".")[-1] not in BOOKKEEPING_KEYS for leaf in paths)
        }
        assert not strays, f"a re-run of identical data changed {strays}"

        # And the comparison is not vacuous: the timestamps really did move.
        assert any(moved.values())
        assert scrub_snapshot(after) == scrub_snapshot(before)

    def test_the_comparison_can_see_a_real_change(self, client):
        """A guard on the guard. If the entries above were all bookkeeping, every
        assertion in this class would pass while ignoring the data entirely."""
        seed()
        before = snapshot(client)

        LMArenaEntry.objects.filter(model_key="claude-opus-5-high", category="document").update(
            rank=99
        )
        after = snapshot(client)

        moved = differing_paths(before["/overview/"][1], after["/overview/"][1])
        assert any("document" in path and path.endswith("rank") for path in moved), (
            f"an edited rank did not show up in the comparison: {sorted(moved)}"
        )


# --------------------------------------------------------------------------- #
# A failed refresh changes nothing but the status
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestAFailedRefresh:
    def test_every_served_row_survives_a_failed_refresh_unchanged(self, client):
        """The central promise of the read path.

        AA is down and the refresh fails. The frontend keeps rendering exactly
        what it rendered before -- not an empty board, not nulls, not a 500 --
        because the read path never consults AA in the first place.

        The assertion is per-leaf rather than a whole-body comparison, so it can
        state the two halves separately: *nothing under `results` moved*, and the
        only thing that did move is the status report in `meta`.
        """
        seed()
        before = snapshot(client)

        run = refresh.refresh_aa(client=dead_aa_client(), use_lock=False)
        after = snapshot(client)

        assert run.status == SyncStatus.FAILED.value
        assert run.error_code == "transport_error"

        strays: dict[str, list[str]] = {}
        for path in ALL_ENDPOINTS:
            moved = differing_paths(before[path][1], after[path][1])
            if moved:
                strays[path] = sorted(moved)

        for path, paths in strays.items():
            assert not [leaf for leaf in paths if leaf.startswith("results")], (
                f"{path} served different rows after a failed refresh: {paths}"
            )
            assert all(
                leaf == "meta.generated_at"
                or leaf.startswith(f"meta.sources.{Source.ARTIFICIAL_ANALYSIS.value}.")
                for leaf in paths
            ), f"{path} changed something other than the AA status block: {paths}"

        # The failed attempt is genuinely reported, not silently skipped...
        assert any(
            "meta.sources.artificial_analysis.last_status" in paths for paths in strays.values()
        )
        # ...and it did not touch the last good time.
        assert not any(
            "meta.sources.artificial_analysis.last_success_at" in paths
            for paths in strays.values()
        )

    def test_every_row_is_byte_identical_when_scrubbed_of_the_clock(self, client):
        """The same fact, stated the blunt way: bodies equal but for `generated_at`
        and `age_seconds`.

        Both tests exist because they fail differently: the per-leaf one names
        what moved, this one cannot miss a field the first forgot to enumerate.
        """
        seed()
        before = snapshot(client)

        refresh.refresh_aa(client=dead_aa_client(), use_lock=False)
        after = snapshot(client)

        # The per-source status block is the *point* of `/metadata/`-style
        # freshness, so it is compared separately; here only `/metadata/` itself
        # would carry it, and it is not in the snapshot.
        for path in ALL_ENDPOINTS:
            left = copy.deepcopy(before[path][1])
            right = copy.deepcopy(after[path][1])
            for body in (left, right):
                body.pop("meta", None)
            assert right == left, f"{path} served different data after a failed refresh"

    def test_metadata_reports_the_failure_while_keeping_the_last_good_time(self, client):
        """Both facts, side by side. A frontend must be able to say "data as of
        this morning; the noon refresh failed" rather than choosing one."""
        seed()
        source = Source.ARTIFICIAL_ANALYSIS.value
        good = client.get(f"{BASE}/metadata/").json()["sources"][source]

        refresh.refresh_aa(client=dead_aa_client(), use_lock=False)
        state = client.get(f"{BASE}/metadata/").json()["sources"][source]

        assert state["last_status"] == SyncStatus.FAILED.value
        assert state["last_success_at"] == good["last_success_at"]
        assert state["last_error"]["code"] == "transport_error"
        assert state["is_stale"] is False, (
            "a failed attempt does not make good data stale -- it makes the run failed"
        )

    def test_the_failed_run_is_visible_to_operators_in_recent_runs(self, client):
        seed()
        before = len(client.get(f"{BASE}/metadata/").json()["recent_runs"])

        refresh.refresh_aa(client=dead_aa_client(), use_lock=False)
        recent = client.get(f"{BASE}/metadata/").json()["recent_runs"]

        assert len(recent) > before
        assert recent[0]["status"] == SyncStatus.FAILED.value
        assert recent[0]["source"] == Source.ARTIFICIAL_ANALYSIS.value

    def test_the_quota_echo_is_absent_rather_than_zeroed(self, client):
        """The failure happened before any response came back, so there is no
        quota snapshot to report. `null` says "unknown"; `0` would say "none
        left", which is a different and far more alarming claim."""
        seed()

        refresh.refresh_aa(client=dead_aa_client(), use_lock=False)
        state = client.get(f"{BASE}/metadata/").json()["sources"][
            Source.ARTIFICIAL_ANALYSIS.value
        ]

        assert state["rate_limit"]["remaining"] is None
        assert state["rate_limit"]["limit"] is None


# --------------------------------------------------------------------------- #
# The recovery path
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestAliasPromotion:
    """What a reviewer does about a model the ladder refused to guess at.

    `gpt-5-5-xhigh` is in LMArena's `agent` split with no AA counterpart, so the
    completeness rule excludes it from `/overview/` and it 404s from
    `/models/{key}/`. Recovering it is a `ModelAlias` -- a human saying "these
    two records are the same model".

    The alias is consumed by the match ladder, which runs during a refresh, so
    the promotion lands on the **next** refresh rather than mid-request. That is
    deliberate, not a shortfall: it keeps the served join a stored fact that
    `/overview/`, `/models/{key}/` and `/unmatched/` all agree on, instead of a
    per-request inference that could differ between endpoints. A reviewer applies
    it at once with one command rather than waiting for the schedule; what they
    never need is a deploy, a code change or a backfill job.
    """

    def _add_alias(self) -> None:
        ModelAlias.objects.create(
            source=Source.ARTIFICIAL_ANALYSIS.value,
            category="agent",
            raw_name="Unrelated Model",
            canonical_key="gpt-5-5-xhigh",
            note="AA measures this model; the agent split spells it differently.",
        )

    def test_the_alias_is_not_resolved_mid_request(self, client):
        """The honest limitation, pinned so it cannot drift into a claim.

        Nothing about the stored match set has changed yet, so nothing about the
        served data changes yet -- even though the alias row now exists.
        """
        seed()
        before = snapshot(client)

        self._add_alias()
        after = snapshot(client)

        # No refresh ran, so not one bookkeeping field may have moved either --
        # the narrow key set, not the wide one.
        assert scrub_snapshot(after, REQUEST_CLOCK_KEYS) == scrub_snapshot(
            before, REQUEST_CLOCK_KEYS
        )
        assert client.get(f"{BASE}/overview/").json()["count"] == 2

    def test_the_next_refresh_promotes_it_with_its_provenance(self, client):
        """Afterwards the entry is complete, marked manual, and carries the AA
        values a human asserted belong to it."""
        seed()
        self._add_alias()

        # `seed()` *is* a pipeline run -- the same fakes driven through the same
        # `refresh_all` the schedule calls -- so calling it again is precisely
        # what the next refresh does.
        seed()

        body = client.get(f"{BASE}/overview/").json()
        row = next(
            (item for item in body["results"] if item["model"]["key"] == "gpt-5-5-xhigh"),
            None,
        )

        assert row is not None, "the aliased model did not appear on /overview/"
        assert row["match"]["method"] == "alias"
        assert row["match"]["is_manual"] is True
        assert row["aa"]["slug"] == "unrelated-model"
        assert row["aa"]["id"] == "uuid-orphan"

    def test_direct_detail_lookup_agrees_with_the_list(self, client):
        """The 404 becomes a 200, and the two surfaces describe the same join.
        The failure mode this design avoids is a model that appears in a list
        while its own page says it does not exist."""
        seed()
        self._add_alias()
        seed()

        response = client.get(f"{BASE}/models/gpt-5-5-xhigh/")

        assert response.status_code == 200
        detail = response.json()
        assert detail["model"]["key"] == "gpt-5-5-xhigh"
        assert detail["match"]["method"] == "alias"

    def test_the_dropped_row_is_reported_with_the_reason_the_404_cites(self, client):
        """A model `/overview/` drops must be findable by name from `/unmatched/`.

        Otherwise the completeness rule's exclusions are invisible precisely
        where a reviewer looks for them -- the frontend sees a model vanish from
        the joined list with nothing anywhere saying why.
        """
        seed()

        response = client.get(f"{BASE}/models/gpt-5-5-xhigh/")
        cites = response.json()["detail"]["unmatched"]
        assert response.status_code == 404
        assert cites["reason"] == "no_aa_match"

        body = client.get(f"{BASE}/unmatched/?reason=no_aa_match").json()
        assert [row["model_key"] for row in body["results"]] == ["gpt-5-5-xhigh"]
        assert body["results"][0]["model_name"] == "GPT 5.5 (xHigh)"
        assert body["results"][0]["category"] == "agent"

    def test_the_alias_also_clears_the_agent_side_entry(self, client):
        """Both directions of the miss retire together on promotion: the AA
        record finds a home, and the agent row finds a partner."""
        seed()
        assert client.get(f"{BASE}/unmatched/?reason=no_aa_match").json()["count"] == 1

        self._add_alias()
        seed()

        assert client.get(f"{BASE}/unmatched/?reason=no_aa_match").json()["count"] == 0

    def test_the_alias_clears_the_stale_ledger_entry(self, client):
        """The ledger is rebuilt, not appended to, so the promotion removes the
        AA-side `no_lmarena_match` row rather than leaving a stale one behind."""
        seed()
        before = client.get(f"{BASE}/unmatched/?source=artificial_analysis").json()
        assert before["count"] == 1

        self._add_alias()
        seed()

        after = client.get(f"{BASE}/unmatched/?source=artificial_analysis").json()
        assert after["results"] == []
        assert after["count"] == 0


# --------------------------------------------------------------------------- #
# The response contract, checked on the wire
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestWireFormat:
    """Types that only exist once a response is serialized and parsed back.

    Every assertion here is about JSON rather than about Python: `Decimal` is not
    JSON-serializable, `null` is not `0`, and a naive `json.dumps` of either
    would pass a `response.data` assertion while breaking the frontend.
    """

    def test_the_body_round_trips_through_json(self, client):
        seed()

        for path, (_, body) in snapshot(client).items():
            assert json.loads(json.dumps(body)) == body, f"{path} is not plain JSON"

    def test_money_survives_the_round_trip_as_a_number(self, client):
        """A cost emitted as the string "59.99" would quietly become a
        categorical axis in D3 rather than a continuous one."""
        seed()

        row = client.get(f"{BASE}/overview/").json()["results"][0]

        assert isinstance(row["aa"]["intelligence_index_total_cost"], (int, float))

    def test_an_unmeasured_value_is_null_and_never_zero(self, client):
        """The distinction the AA schema is explicit about, and the one a chart
        gets wrong: an unmeasured cost is not a free model."""
        seed()

        row = next(
            item
            for item in client.get(f"{BASE}/overview/").json()["results"]
            if item["model"]["key"] == "claude-opus-5-low"
        )

        assert row["aa"]["cost_per_task"] is None
        assert row["aa"]["pricing"]["price_1m_input_tokens"] is None

    def test_every_timestamp_on_the_wire_is_utc_iso8601(self, client):
        """One format, everywhere, so the frontend has one parser and no
        timezone bugs: the API is UTC regardless of the schedule's Asia/Shanghai
        or the database's local time."""
        seed()

        meta = client.get(f"{BASE}/overview/").json()["meta"]
        detail = client.get(f"{BASE}/models/claude-opus-5-high/").json()

        assert meta["generated_at"].endswith("Z")
        assert meta["sources"][Source.LMARENA.value]["last_success_at"].endswith("Z")
        assert detail["aa"]["last_synced_at"].endswith("Z")
        assert detail["provenance"]["lmarena_last_synced_at"].endswith("Z")
        for source in detail["provenance"]["category_sources"].values():
            assert source["last_synced_at"].endswith("Z")

    def test_the_error_envelope_is_consistent_across_status_codes(self, client):
        """The frontend branches on `error`, so every failure -- ours or DRF's --
        has to carry one."""
        seed()

        cases = {
            "/categories/nope/": 404,
            "/models/nope/": 404,
            "/models/gpt-5-5-xhigh/": 404,
            "/overview/?page_size=abc": 400,
            "/overview/?ordering=nope": 400,
        }
        for path, expected in cases.items():
            response = client.get(f"{BASE}{path}")
            body = response.json()
            assert response.status_code == expected, path
            assert isinstance(body.get("error"), str), f"{path} has no `error` string"
            assert body["error"] != "error", (
                f"{path} fell through to the generic code -- the handler replaced "
                "a specific error with a default"
            )


def test_the_body_comparator_can_see_a_difference():
    """A meta-test, because a broken comparator is invisible otherwise.

    `differing_paths` is the mechanism behind the strongest assertions in this
    module. If it returned an empty set for any input, every "nothing changed"
    test here would pass while the data changed completely.
    """
    before = {"a": {"b": 1, "c": None}, "d": [1, 2]}
    after = copy.deepcopy(before)

    assert differing_paths(before, after) == set()

    after["a"]["b"] = 2
    after["d"][1] = 3
    assert differing_paths(before, after) == {"a.b", "d.1"}
