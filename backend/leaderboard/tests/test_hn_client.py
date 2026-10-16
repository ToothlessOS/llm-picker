"""The Hacker News client: URL construction, the guards, and the error mapping.

Everything here is exercised through `FakeTransport`, so the tests assert *our*
retry loop, *our* pagination and *our* guards rather than a library's
interception machinery. The three guards get the most attention because each one
exists for a documented property of this API that fails *silently* -- a truncated
result set that looks complete, an enormous body, a page count that stops
mattering at 1,000.
"""

from __future__ import annotations

import pytest

from leaderboard.clients.exceptions import (
    AuthenticationError,
    EmptyResponseError,
    PayloadTooLargeError,
    PaginationGuardError,
    RateLimitError,
    SchemaError,
    SourceError,
    TransportError,
    UpstreamServerError,
)
from leaderboard.clients.hackernews import (
    ITEMS_PATH,
    SEARCH_BY_DATE_PATH,
    USER_AGENT,
    HackerNewsClient,
)
from leaderboard.clients.http import RetryPolicy
from leaderboard.tests.fakes import DEFAULT_HN_TIMESTAMP, FakeResponse, FakeTransport, SleepRecorder, hn_search_page, hn_story_hit


def build(responses, **overrides):
    """A client over a scripted transport, with sleeps recorded not performed."""
    transport = FakeTransport(responses)
    sleep = SleepRecorder()
    client = HackerNewsClient(
        transport=transport,
        sleep=sleep,
        uniform=lambda low, high: high,
        **overrides,
    )
    return client, transport, sleep


def window(client, **overrides):
    params = {"start": 1_000_000, "end": 2_000_000, "min_points": 100, "min_comments": 20}
    params.update(overrides)
    return client.search_window(**params)


class TestDiscoveryRequest:
    def test_asks_search_by_date_for_stories(self):
        client, transport, _ = build([hn_search_page([hn_story_hit(1, "t")])])
        window(client)

        call = transport.calls[0]
        assert call["url"].endswith(SEARCH_BY_DATE_PATH)
        assert call["params"]["tags"] == "story"

    def test_applies_the_floor_server_side(self):
        """The floor is what makes a window affordable: the alternative is
        fetching every story of the period and discarding almost all of them."""
        client, transport, _ = build([hn_search_page([hn_story_hit(1, "t")])])
        window(client, start=111, end=222, min_points=150, min_comments=40)

        filters = transport.calls[0]["params"]["numericFilters"]
        assert filters == "created_at_i>111,created_at_i<222,points>=150,num_comments>=40"

    def test_omits_the_query_parameter_for_a_window(self):
        """No query means "everything in the slice", which is the point."""
        client, transport, _ = build([hn_search_page([hn_story_hit(1, "t")])])
        window(client)

        assert "query" not in transport.calls[0]["params"]

    def test_a_term_sweep_sends_the_query_and_a_lower_floor(self):
        """The floor is applied server-side like the window's, but it is a
        *different, lower* one: "below the top stories of the week" and "trivia"
        are separate thresholds, and a sweep with no floor at all drags in threads
        with two points and three comments."""
        client, transport, _ = build([hn_search_page([hn_story_hit(1, "t")])])
        client.search_term(term="claude", since=999, min_points=30, min_comments=5)

        params = transport.calls[0]["params"]
        assert params["query"] == "claude"
        assert params["numericFilters"] == (
            "created_at_i>999,points>=30,num_comments>=5"
        )

    def test_a_term_sweep_defaults_to_no_floor(self):
        """The floor is the caller's to set -- the client does not invent a policy."""
        client, transport, _ = build([hn_search_page([hn_story_hit(1, "t")])])
        client.search_term(term="claude", since=999)

        assert transport.calls[0]["params"]["numericFilters"] == (
            "created_at_i>999,points>=0,num_comments>=0"
        )

    def test_identifies_itself(self):
        """An anonymous client is the kind that gets throttled first."""
        client, transport, _ = build([hn_search_page([hn_story_hit(1, "t")])])
        window(client)

        assert transport.calls[0]["headers"]["User-Agent"] == USER_AGENT

    def test_reads_the_story_tree_from_the_items_path(self):
        client, transport, _ = build([FakeResponse(200, {"id": 7, "children": []})])
        client.fetch_item(7)

        assert transport.calls[0]["url"].endswith(f"{ITEMS_PATH}/7")

    def test_comment_trees_get_their_own_longer_timeout(self):
        """A 600-comment tree legitimately needs longer than a search page."""
        client, transport, _ = build(
            [FakeResponse(200, {"id": 7, "children": []})],
            timeout=10.0,
            tree_timeout=99.0,
        )
        client.fetch_item(7)

        assert transport.calls[0]["timeout"] == 99.0


class TestPagination:
    def test_follows_pages_until_the_api_reports_no_more(self):
        responses = [
            hn_search_page([hn_story_hit(i, f"t{i}") for i in range(3)], page=0, nb_hits=5),
            hn_search_page([hn_story_hit(i, f"t{i}") for i in range(3, 5)], page=1, nb_hits=5),
        ]
        # nbPages is what stops it; the fake reports a single page, so drive it
        # through nbHits/nbPages explicitly instead.
        responses[0]._payload["nbPages"] = 2
        responses[1]._payload["nbPages"] = 2
        client, transport, _ = build(responses)

        result = window(client)

        assert [call["params"]["page"] for call in transport.calls] == [0, 1]
        assert len(result.hits) == 5
        assert result.pages_fetched == 2

    def test_stops_at_the_configured_page_limit(self):
        responses = [hn_search_page([hn_story_hit(i, "t")], page=i, nb_hits=999, hits_per_page=1) for i in range(5)]
        for index, response in enumerate(responses):
            response._payload["nbPages"] = 999
        client, transport, _ = build(responses, hits_per_page=1, max_page=3)

        result = window(client)

        assert len(transport.calls) == 3
        assert result.pages_fetched == 3

    def test_reports_truncation_when_it_saw_fewer_hits_than_exist(self):
        """The honest form: a caller that saw part of a window must not present a
        top-10 as though it had seen everything."""
        response = hn_search_page([hn_story_hit(1, "t")], nb_hits=900)
        response._payload["nbPages"] = 99
        client, _, _ = build([response], max_page=1)

        result = window(client)

        assert result.nb_hits == 900
        assert result.truncated is True

    def test_is_not_truncated_when_it_saw_everything(self):
        response = hn_search_page([hn_story_hit(1, "t")], nb_hits=1)
        client, _, _ = build([response])

        assert window(client).truncated is False

    def test_stops_on_an_empty_page(self):
        """A short final page is how the API signals the end when `nbPages` is
        absent, which is why the loop cannot rely on a page count alone."""
        first = hn_search_page([hn_story_hit(1, "t")], page=0, nb_hits=2)
        first._payload.pop("nbPages")
        second = hn_search_page([], page=1, nb_hits=2)
        client, transport, _ = build([first, second])

        result = window(client)

        assert len(transport.calls) == 2
        assert len(result.hits) == 1


class TestPaginationCeiling:
    def test_refuses_a_page_the_api_cannot_serve_honestly(self):
        """Past 1,000 results the API returns a shorter list *as though it were
        the whole thing*, so truncation is indistinguishable from a small result
        set. Failing is the only way to keep completeness meaningful.

        Driven with a callable transport because the guard's whole point is that
        the API would keep answering -- scripted responses would run out first and
        the test would pass for the wrong reason.
        """

        def always_more(index: int):
            response = hn_search_page([hn_story_hit(index, "t")], page=index, nb_hits=10**6, hits_per_page=1000)
            response._payload["nbPages"] = 10**6
            return response

        # 1000 per page permits exactly one page before the ceiling.
        client, transport, _ = build(always_more, hits_per_page=1000, max_page=5)

        with pytest.raises(PaginationGuardError) as excinfo:
            window(client)

        assert excinfo.value.detail == {"page": 1, "hits_per_page": 1000, "ceiling": 1000}
        assert len(transport.calls) == 1

    def test_the_default_configuration_stays_inside_the_ceiling(self):
        """9 pages of 100 is 900, comfortably under the 1,000 ceiling -- which is
        the arithmetic `checks.py` asserts at boot so the guard is never reached."""
        client, _, _ = build([], hits_per_page=100, max_page=9)

        assert client.max_pages_within_ceiling == 10
        assert client.max_pages_within_ceiling > 9

    def test_a_single_page_vocabulary_still_permits_one_request(self):
        """`max(1, ...)` matters: a hits_per_page above the ceiling must not make
        the very first page unrequestable."""
        client, _, _ = build([], hits_per_page=5000)

        assert client.max_pages_within_ceiling == 1


class TestEmptyWindowIsAnError:
    def test_a_window_with_no_stories_fails_the_run(self):
        """Hacker News always has hundreds of stories above the floor in a week.
        Zero means the filters stopped meaning what we think, not a quiet period."""
        client, _, _ = build([hn_search_page([])])

        with pytest.raises(EmptyResponseError) as excinfo:
            window(client)

        assert excinfo.value.detail["min_points"] == 100

    def test_a_term_sweep_matching_nothing_is_normal(self):
        """The asymmetry is deliberate: one term having no hits is the ordinary
        case and must never fail an hourly run."""
        client, _, _ = build([hn_search_page([])])

        assert client.search_term(term="nonexistent", since=1).hits == []


class TestRetriesAndStatusMapping:
    def test_retries_a_transport_failure_then_succeeds(self):
        client, transport, sleep = build(
            [TransportError("connection reset"), hn_search_page([hn_story_hit(1, "t")])]
        )

        assert len(window(client).hits) == 1
        assert len(transport.calls) == 2
        assert sleep.total > 0

    def test_gives_up_after_the_retry_budget(self):
        client, _, _ = build([TransportError("down")] * 4, retry_policy=RetryPolicy(max_attempts=3))

        with pytest.raises(TransportError):
            window(client)

    def test_retries_a_5xx_then_succeeds(self):
        client, transport, _ = build(
            [FakeResponse(503, {}), hn_search_page([hn_story_hit(1, "t")])]
        )

        assert len(window(client).hits) == 1
        assert len(transport.calls) == 2

    def test_a_persistent_5xx_is_an_upstream_error(self):
        client, _, _ = build([FakeResponse(500, {})] * 4, retry_policy=RetryPolicy(max_attempts=2))

        with pytest.raises(UpstreamServerError):
            window(client)

    def test_does_not_retry_a_permanent_4xx(self):
        """Retrying cannot help, and a retry storm is how a client gets blocked."""
        client, transport, _ = build([FakeResponse(400, {})])

        with pytest.raises(SourceError):
            window(client)
        assert len(transport.calls) == 1

    def test_a_403_is_an_authentication_error_not_a_retry(self):
        client, transport, _ = build([FakeResponse(403, {})])

        with pytest.raises(AuthenticationError):
            window(client)
        assert len(transport.calls) == 1

    def test_a_short_retry_after_is_slept_through(self):
        client, transport, sleep = build(
            [
                FakeResponse(429, {}, headers={"Retry-After": "5"}),
                hn_search_page([hn_story_hit(1, "t")]),
            ],
            max_inline_retry_after_seconds=60,
        )

        assert len(window(client).hits) == 1
        assert sleep.durations == [5.0]

    def test_a_long_retry_after_fails_instead_of_sleeping_through_the_window(self):
        """Sleeping ~20 h inside a worker is worse than an honest failure the next
        hourly run recovers from."""
        client, _, sleep = build(
            [FakeResponse(429, {}, headers={"Retry-After": "7200"})],
            max_inline_retry_after_seconds=60,
        )

        with pytest.raises(RateLimitError) as excinfo:
            window(client)
        assert excinfo.value.retry_after == 7200
        assert sleep.durations == []

    def test_an_http_date_retry_after_is_understood(self):
        from datetime import datetime, timedelta, timezone

        soon = datetime.now(tz=timezone.utc) + timedelta(seconds=30)
        client, _, sleep = build(
            [
                FakeResponse(429, {}, headers={"Retry-After": soon.strftime("%a, %d %b %Y %H:%M:%S GMT")}),
                hn_search_page([hn_story_hit(1, "t")]),
            ]
        )

        window(client)
        assert sleep.durations and 0 <= sleep.durations[0] <= 30


class TestSchemaGuards:
    def test_a_search_body_without_hits_is_a_schema_error(self):
        client, _, _ = build([FakeResponse(200, {"nbHits": 0})])

        with pytest.raises(SchemaError):
            window(client)

    def test_a_non_json_body_is_a_schema_error(self):
        client, _, _ = build([FakeResponse(200, [1, 2, 3])])

        with pytest.raises(SchemaError):
            window(client)

    def test_an_item_body_that_is_not_an_object_is_a_schema_error(self):
        client, _, _ = build([FakeResponse(200, "nope")])

        with pytest.raises(SchemaError):
            client.fetch_item(1)

    def test_an_undecodable_body_is_a_schema_error(self):
        client, _, _ = build([FakeResponse(200, ValueError("not json"))])

        with pytest.raises(SchemaError):
            window(client)

    def test_a_non_mapping_hit_is_skipped_rather_than_fatal(self):
        """One malformed entry must not cost the whole window."""
        response = hn_search_page([hn_story_hit(1, "t")])
        response._payload["hits"].append("garbage")
        client, _, _ = build([response])

        assert len(window(client).hits) == 1


class TestPayloadSizeGuard:
    def test_refuses_an_oversized_body_before_reading_it(self):
        """A thousand-comment thread is megabytes of JSON; refusing on
        Content-Length avoids downloading it at all."""
        client, _, _ = build(
            [FakeResponse(200, {"id": 1}, headers={"Content-Length": "9000000"})],
            max_item_bytes=8_000_000,
        )

        with pytest.raises(PayloadTooLargeError) as excinfo:
            client.fetch_item(1)

        assert excinfo.value.detail["content_length"] == 9000000

    def test_allows_a_body_within_the_ceiling(self):
        client, _, _ = build(
            [FakeResponse(200, {"id": 1}, headers={"Content-Length": "100"})],
            max_item_bytes=8_000_000,
        )

        assert client.fetch_item(1) == {"id": 1}

    def test_an_absent_content_length_cannot_help_and_does_not_block(self):
        """A chunked response has no length to check, which is exactly why the
        ingest-side comment cap exists as a second guard."""
        client, _, _ = build([FakeResponse(200, {"id": 1})])

        assert client.fetch_item(1) == {"id": 1}

    def test_an_unparseable_content_length_is_ignored(self):
        client, _, _ = build([FakeResponse(200, {"id": 1}, headers={"Content-Length": "abc"})])

        assert client.fetch_item(1) == {"id": 1}


class TestRequestAccounting:
    def test_counts_the_requests_it_spends(self):
        """Nothing here needs a key, so the request count is the only cost a run
        has to report."""
        responses = [hn_search_page([hn_story_hit(1, "t")], page=0, nb_hits=2)]
        responses[0]._payload["nbPages"] = 2
        client, _, _ = build([responses[0], hn_search_page([hn_story_hit(2, "t")], page=1, nb_hits=2)])

        window(client)

        assert client.requests_made == 2

    def test_a_failed_attempt_still_counts_as_a_request(self):
        client, _, _ = build([FakeResponse(503, {}), hn_search_page([hn_story_hit(1, "t")])])

        window(client)

        assert client.requests_made == 2


def test_the_default_timestamp_fixture_is_stable():
    """Several suites slice windows against it, so it must not drift silently."""
    assert DEFAULT_HN_TIMESTAMP == 1_760_000_000
