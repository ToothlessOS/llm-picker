"""External retrieval: pagination, retry policy, quota accounting, schema safety.

The Artificial Analysis budget is 100 requests / 24h shared across the whole
organisation, so a retry-loop bug is not a performance problem -- it is an
outage. Several tests below assert on the *exact number of calls made*, which is
the only way to catch a loop that retries one time too many.

The LMArena loader is injected rather than imported, so nothing here triggers a
Hugging Face download and `datasets` is never imported.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from leaderboard.clients.artificial_analysis import ArtificialAnalysisClient
from leaderboard.clients.exceptions import (
    AuthenticationError,
    EmptyResponseError,
    PaginationGuardError,
    RateLimitError,
    SchemaError,
    SourceError,
    TransportError,
    UpstreamServerError,
)
from leaderboard.clients.http import RetryPolicy
from leaderboard.clients.lmarena import LMArenaClient
from leaderboard.tests.fakes import (
    FakeLoader,
    FakeResponse,
    FakeTransport,
    SleepRecorder,
    TransientLoaderError,
    aa_model,
    aa_page,
    loaded,
    upper_bound_uniform,
)


def build_client(transport, *, sleep=None, max_pages=8, policy=None, **kwargs):
    return ArtificialAnalysisClient(
        "test-key",
        transport=transport,
        sleep=sleep or SleepRecorder(),
        uniform=upper_bound_uniform,
        retry_policy=policy or RetryPolicy(max_attempts=4, base_delay=1.0, max_delay=30.0),
        max_pages=max_pages,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Artificial Analysis
# --------------------------------------------------------------------------- #


class TestAaPagination:
    def test_follows_pages_until_has_more_is_false(self):
        transport = FakeTransport(
            [
                aa_page([aa_model(f"id-{i}", f"slug-{i}", f"Model {i}") for i in range(2)],
                        page=1, has_more=True, total_pages=3),
                aa_page([aa_model("id-2", "slug-2", "Model 2")], page=2, has_more=True, total_pages=3),
                aa_page([aa_model("id-3", "slug-3", "Model 3")], page=3, has_more=False, total_pages=3),
            ]
        )

        result = build_client(transport).fetch_all_models()

        assert transport.pages_requested == [1, 2, 3]
        assert result.pages_fetched == 3
        assert len(result.records) == 4

    def test_sends_the_key_and_asks_for_one_page_at_a_time(self):
        transport = FakeTransport([aa_page([aa_model("i", "s", "N")])])

        build_client(transport).fetch_all_models()

        assert transport.calls[0]["headers"]["x-api-key"] == "test-key"
        assert transport.calls[0]["params"] == {"page": 1}

    def test_pagination_guard_stops_a_runaway_has_more(self):
        """An upstream bug reporting `has_more` forever must not drain quota.

        Without the guard this loop spends all 100 requests in seconds. The
        scripted transport also caps the test: a 9th call would fail.
        """
        transport = FakeTransport(
            lambda i: aa_page([aa_model(f"id-{i}", f"slug-{i}", f"Model {i}")], page=i + 1, has_more=True)
        )

        with pytest.raises(PaginationGuardError):
            build_client(transport, max_pages=8).fetch_all_models()

        assert len(transport.calls) == 8

    def test_empty_catalogue_raises_rather_than_returning_nothing(self):
        """A 200 with zero models is a bad response, not an empty board.

        Returning `[]` here is what would let a deactivation pass blank the
        whole leaderboard.
        """
        transport = FakeTransport([aa_page([])])

        with pytest.raises(EmptyResponseError):
            build_client(transport).fetch_all_models()

    def test_missing_data_array_is_a_schema_error(self):
        transport = FakeTransport([FakeResponse(200, {"pagination": {"has_more": False}})])

        with pytest.raises(SchemaError):
            build_client(transport).fetch_all_models()

    def test_missing_pagination_object_is_a_schema_error(self):
        transport = FakeTransport([FakeResponse(200, {"data": []})])

        with pytest.raises(SchemaError):
            build_client(transport).fetch_all_models()

    def test_non_json_body_is_a_schema_error(self):
        transport = FakeTransport([FakeResponse(200, ValueError("not json"))])

        with pytest.raises(SchemaError):
            build_client(transport).fetch_all_models()


class TestAaRetryPolicy:
    def test_server_errors_are_retried_with_growing_capped_backoff(self):
        sleeps = SleepRecorder()
        transport = FakeTransport(
            [
                FakeResponse(500),
                FakeResponse(500),
                FakeResponse(503),
                aa_page([aa_model("i", "s", "N")]),
            ]
        )

        build_client(transport, sleep=sleeps).fetch_all_models()

        assert len(transport.calls) == 4
        # Ceilings for attempts 1, 2, 3: 1s, 2s, 4s -- capped at max_delay.
        assert sleeps.durations == [1.0, 2.0, 4.0]

    def test_backoff_is_capped_at_max_delay(self):
        sleeps = SleepRecorder()
        transport = FakeTransport([FakeResponse(500)] * 5 + [aa_page([aa_model("i", "s", "N")])])

        build_client(
            transport,
            sleep=sleeps,
            policy=RetryPolicy(max_attempts=6, base_delay=10.0, max_delay=30.0),
        ).fetch_all_models()

        # Ceilings would be 10, 20, 40, 80, 160 -- capped to 30 after the second.
        assert sleeps.durations == [10.0, 20.0, 30.0, 30.0, 30.0]

    def test_transport_errors_are_retried(self):
        sleeps = SleepRecorder()
        transport = FakeTransport(
            [TransportError("connection reset"), aa_page([aa_model("i", "s", "N")])]
        )

        build_client(transport, sleep=sleeps).fetch_all_models()

        assert len(transport.calls) == 2
        assert sleeps.durations == [1.0]

    def test_server_error_gives_up_after_the_attempt_budget(self):
        sleeps = SleepRecorder()
        transport = FakeTransport([FakeResponse(500)] * 4)

        with pytest.raises(UpstreamServerError):
            build_client(transport, sleep=sleeps).fetch_all_models()

        assert len(transport.calls) == 4
        assert len(sleeps.durations) == 3

    def test_auth_failure_is_not_retried(self):
        """401 means the key is wrong; retrying cannot change that."""
        transport = FakeTransport([FakeResponse(401)])

        with pytest.raises(AuthenticationError):
            build_client(transport).fetch_all_models()

        assert len(transport.calls) == 1

    def test_other_client_errors_are_not_retried(self):
        transport = FakeTransport([FakeResponse(422)])

        with pytest.raises(SourceError):
            build_client(transport).fetch_all_models()

        assert len(transport.calls) == 1

    def test_missing_key_fails_before_any_request(self):
        """A missing key must not break the read-only API -- it only fails AA."""
        transport = FakeTransport([])
        client = ArtificialAnalysisClient(None, transport=transport, sleep=SleepRecorder())

        assert client.configured is False
        with pytest.raises(AuthenticationError):
            client.fetch_all_models()
        assert transport.calls == []


class TestAaRateLimit:
    def test_short_retry_after_is_honoured_inline(self):
        sleeps = SleepRecorder()
        transport = FakeTransport(
            [
                FakeResponse(429, {"error": "slow down"}, {"Retry-After": "5"}),
                aa_page([aa_model("i", "s", "N")]),
            ]
        )

        build_client(transport, sleep=sleeps).fetch_all_models()

        assert len(transport.calls) == 2
        assert sleeps.durations == [5.0]

    def test_long_retry_after_aborts_with_zero_further_calls(self):
        """Sleeping ~20h inside a worker is strictly worse than an honest failure.

        The next scheduled run picks it up; the metadata endpoint explains it.
        """
        sleeps = SleepRecorder()
        transport = FakeTransport([FakeResponse(429, {}, {"Retry-After": "3600"})])

        with pytest.raises(RateLimitError) as excinfo:
            build_client(transport, sleep=sleeps).fetch_all_models()

        assert len(transport.calls) == 1
        assert sleeps.durations == []
        assert excinfo.value.retry_after == 3600

    def test_rate_limit_headers_are_parsed_into_an_aware_utc_datetime(self):
        transport = FakeTransport(
            [
                aa_page(
                    [aa_model("i", "s", "N")],
                    tier="free",
                    headers={
                        "X-RateLimit-Limit": "100",
                        "X-RateLimit-Remaining": "82",
                        "X-RateLimit-Reset": "1789200000",
                        "X-AA-Tier": "free",
                    },
                )
            ]
        )

        snapshot = build_client(transport).fetch_all_models().rate_limit

        assert snapshot.limit == 100
        assert snapshot.remaining == 82
        assert snapshot.reset_at == datetime.fromtimestamp(1789200000, tz=timezone.utc)
        assert snapshot.reset_at.tzinfo is timezone.utc

    def test_quota_is_captured_even_when_the_response_fails(self):
        """The numbers are what explain the failure, so read them first."""
        transport = FakeTransport(
            [FakeResponse(401, {}, {"X-RateLimit-Remaining": "0", "X-AA-Tier": "free"})]
        )
        client = build_client(transport)

        with pytest.raises(AuthenticationError):
            client.fetch_all_models()

        assert client.last_rate_limit.remaining == 0

    def test_header_names_are_matched_case_insensitively(self):
        transport = FakeTransport(
            [aa_page([aa_model("i", "s", "N")], headers={"x-ratelimit-remaining": "7"})]
        )

        assert build_client(transport).fetch_all_models().rate_limit.remaining == 7


# --------------------------------------------------------------------------- #
# LMArena
# --------------------------------------------------------------------------- #


def agent_rows(n: int = 2) -> list[dict]:
    """Rows carrying exactly the columns `required_columns("agent")` demands."""
    return [
        {
            "model_name": f"Model {i}",
            "organization": "org",
            "license": "Proprietary",
            "rank": i + 1,
            "category": "overall",
            "leaderboard_publish_date": "2026-09-01",
            "score": 0.5,
            "score_ci_lower": 0.4,
            "score_ci_upper": 0.6,
            "observation_count": 10,
            "session_count": 5,
        }
        for i in range(n)
    ]


class TestLMArenaClient:
    def test_uses_the_latest_split_only(self):
        """`full` is deliberately unreachable: there is no code path to it."""
        loader = FakeLoader({"agent": loaded(agent_rows())})
        client = LMArenaClient(loader=loader, sleep=SleepRecorder())

        client.fetch_category("agent")

        assert loader.calls == [("lmarena-ai/leaderboard-dataset", "agent")]

    def test_retries_a_transient_loader_failure(self):
        sleeps = SleepRecorder()
        loader = FakeLoader({"agent": loaded(agent_rows())}, fail_times=1)
        client = LMArenaClient(loader=loader, sleep=sleeps, max_attempts=2)

        split = client.fetch_category("agent")

        assert len(split.rows) == 2
        assert len(loader.calls) == 2
        assert sleeps.durations == [2.0]

    def test_gives_up_after_max_attempts(self):
        sleeps = SleepRecorder()
        loader = FakeLoader({"agent": TransientLoaderError("always down")})
        client = LMArenaClient(loader=loader, sleep=sleeps, max_attempts=2)

        with pytest.raises(SourceError):
            client.fetch_category("agent")

        assert len(loader.calls) == 2

    def test_missing_column_is_a_schema_error_and_is_not_retried(self):
        """A schema change is permanent; retrying just wastes time."""
        rows = agent_rows()
        for row in rows:
            row.pop("observation_count")
        loader = FakeLoader({"agent": loaded(rows)})
        client = LMArenaClient(loader=loader, sleep=SleepRecorder())

        with pytest.raises(SchemaError):
            client.fetch_category("agent")

        assert len(loader.calls) == 1

    def test_unknown_category_is_rejected(self):
        loader = FakeLoader({})
        client = LMArenaClient(loader=loader, sleep=SleepRecorder())

        with pytest.raises(SourceError):
            client.fetch_category("not-a-category")
