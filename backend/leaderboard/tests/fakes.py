"""Test doubles for the two external boundaries.

Injected at *our* seams -- the `Transport` protocol and the `load_dataset`
callable -- rather than by patching `requests` or `datasets`. That means these
tests exercise our retry loop, our pagination and our error mapping, instead of
a library's interception machinery. It also means the suite never needs network
access and never imports `datasets`.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence

from leaderboard.clients.exceptions import SourceError
from leaderboard.clients.hackernews import DiscoveryResult
from leaderboard.clients.lmarena import LoadedSplit


class FakeResponse:
    """Enough of `requests.Response` for the client: status, headers, json()."""

    def __init__(
        self,
        status_code: int = 200,
        payload: Any = None,
        headers: Mapping[str, str] | None = None,
    ):
        self.status_code = status_code
        self._payload = payload
        self.headers = dict(headers or {})

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeTransport:
    """A scripted `Transport` that records every call it receives.

    `responses` may be a list of responses (consumed in order) or a callable
    taking the call index. Running past the end of a list raises, so a test can
    assert *how many* calls were made by simply not providing more -- and an
    unscripted extra call fails loudly rather than silently succeeding.
    """

    def __init__(self, responses: Sequence[Any] | Callable[[int], Any]):
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> FakeResponse:
        index = len(self.calls)
        self.calls.append(
            {"url": url, "headers": dict(headers), "params": dict(params or {}), "timeout": timeout}
        )
        if callable(self._responses):
            response = self._responses(index)
        else:
            if index >= len(self._responses):
                raise AssertionError(
                    f"unexpected HTTP call #{index + 1}: the script only provided "
                    f"{len(self._responses)} response(s)"
                )
            response = self._responses[index]
        if isinstance(response, Exception):
            raise response
        return response

    # -- assertions -------------------------------------------------------- #

    @property
    def pages_requested(self) -> list[Any]:
        return [call["params"].get("page") for call in self.calls]


class SleepRecorder:
    """Records requested sleeps instead of performing them.

    A test that asserted on wall-clock time would be slow and flaky; recording
    the durations asserts the *policy* directly.
    """

    def __init__(self) -> None:
        self.durations: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)

    @property
    def total(self) -> float:
        return sum(self.durations)


def upper_bound_uniform(low: float, high: float) -> float:
    """A deterministic stand-in for `random.uniform` returning the ceiling.

    Makes backoff assertions exact: `RetryPolicy.delay_for` computes a ceiling
    and jitters below it, so always taking the ceiling is the strictest reading.
    """
    return high


def aa_page(
    models: Iterable[Mapping[str, Any]],
    *,
    page: int = 1,
    has_more: bool = False,
    page_size: int = 200,
    total_pages: int = 1,
    tier: str = "free",
    version: Any = 4.3,
    headers: Mapping[str, str] | None = None,
    status: int = 200,
) -> FakeResponse:
    """One `/language/models/free` page, shaped like the real thing."""
    return FakeResponse(
        status,
        {
            "data": list(models),
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "has_more": has_more,
            },
            "tier": tier,
            "intelligence_index_version": version,
        },
        headers,
    )


def aa_model(
    identifier: str,
    slug: str,
    name: str,
    **overrides: Any,
) -> dict[str, Any]:
    """A minimal AA model record -- only the three identity fields are required."""
    payload = {"id": identifier, "slug": slug, "name": name}
    payload.update(overrides)
    return payload


class FakeLoader:
    """A stand-in for `load_dataset(dataset_id, field, split="latest")`.

    Records `(dataset_id, field)` per call and returns whatever `splits` holds
    for that field -- or raises the exception placed there, which is how the
    "one field fails, the others still load" cases are set up.
    """

    def __init__(self, splits: Mapping[str, Any], *, fail_times: int = 0):
        self.splits = dict(splits)
        #: Fail the first N calls for a field with a `TransientLoaderError`,
        #: so a retry has something to recover from.
        self.fail_times = fail_times
        self.calls: list[tuple[str, str]] = []
        self._failures: dict[str, int] = {}

    def __call__(self, dataset_id: str, field: str) -> LoadedSplit:
        self.calls.append((dataset_id, field))
        if self.fail_times and self._failures.get(field, 0) < self.fail_times:
            self._failures[field] = self._failures.get(field, 0) + 1
            raise TransientLoaderError(f"transient failure loading {field!r}")
        result = self.splits.get(field)
        if result is None:
            raise AssertionError(f"FakeLoader has no split for {field!r}")
        if isinstance(result, Exception):
            raise result
        return result


class TransientLoaderError(RuntimeError):
    """Stands in for a network-ish failure inside the HF loader."""


def loaded(rows: list[dict[str, Any]], *, columns: Sequence[str] | None = None) -> LoadedSplit:
    """A `LoadedSplit` whose columns are derived from the rows.

    Deriving by default keeps fixtures honest: a test that forgets to add a
    column gets the schema error the real loader would produce, rather than a
    fixture that quietly disagrees with what `check_columns` expects.
    """
    if columns is None:
        seen: list[str] = []
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.append(key)
        columns = seen
    return LoadedSplit(columns=list(columns), rows=[dict(row) for row in rows], revision="test-rev")


# --------------------------------------------------------------------------- #
# Hacker News / Algolia
# --------------------------------------------------------------------------- #

#: Default story timestamp, matching the fixtures the tests were written against.
DEFAULT_HN_TIMESTAMP = 1_760_000_000

_UNSET: Any = object()


def hn_story_hit(
    object_id: Any,
    title: str,
    *,
    url: str = "",
    author: str = "pg",
    points: Any = 300,
    num_comments: Any = 120,
    created_at_i: Any = DEFAULT_HN_TIMESTAMP,
    created_at: Any = None,
    **overrides: Any,
) -> dict[str, Any]:
    """One `/search_by_date` hit, shaped like the real thing.

    `created_at` is derived from `created_at_i` unless a test supplies it -- the
    two are always both present upstream, and a fixture that carried only one
    would let a parsing bug hide.
    """
    payload: dict[str, Any] = {
        "objectID": str(object_id),
        "title": title,
        "url": url,
        "author": author,
        "points": points,
        "num_comments": num_comments,
        "created_at_i": created_at_i,
        "created_at": created_at if created_at is not None else _iso_from(created_at_i),
    }
    payload.update(overrides)
    return payload


def _children_of(children: Any) -> Any:
    """A list for the normal case, and the value untouched otherwise.

    Passing a malformed value straight through is the point: a test needs to be
    able to hand the parser something that is not a list, and coercing it here
    would quietly repair the input the test is trying to break.
    """
    return list(children) if isinstance(children, (list, tuple)) else children


def hn_comment(
    object_id: Any = _UNSET,
    *,
    id: Any = _UNSET,
    author: Any = "commenter",
    text: Any = "a comment",
    children: Any = (),
    points: Any = None,
    created_at_i: Any = DEFAULT_HN_TIMESTAMP,
    **overrides: Any,
) -> dict[str, Any]:
    """One comment node, ready to nest inside `hn_item` or another comment.

    `id` defaults to `object_id` but can be overridden -- including to `None`, to
    stand in for a payload that omits it.
    """
    payload: dict[str, Any] = {
        "id": object_id if id is _UNSET else id,
        "author": author,
        "text": text,
        "points": points,
        "created_at_i": created_at_i,
        "created_at": _iso_from(created_at_i),
        "children": _children_of(children),
    }
    payload.update(overrides)
    return payload


def hn_item(
    object_id: Any,
    *,
    title: str = "Thread",
    children: Any = (),
    text: Any = None,
    url: str = "",
    **overrides: Any,
) -> dict[str, Any]:
    """A `GET /items/{id}` response: the story node, with its comment tree."""
    payload: dict[str, Any] = {
        "id": object_id,
        "type": "story",
        "title": title,
        "url": url,
        "text": text,
        "author": "submitter",
        "points": 300,
        "created_at_i": DEFAULT_HN_TIMESTAMP,
        "created_at": _iso_from(DEFAULT_HN_TIMESTAMP),
        "children": _children_of(children),
    }
    payload.update(overrides)
    return payload


def hn_search_page(
    hits: Iterable[Mapping[str, Any]],
    *,
    page: int = 0,
    nb_hits: int | None = None,
    hits_per_page: int = 100,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
) -> FakeResponse:
    """One Algolia search response.

    `nbHits` defaults to what was supplied, and is overridable so a test can
    simulate the pagination ceiling -- the case where the API reports more hits
    than it will ever hand back.
    """
    materialized = [dict(hit) for hit in hits]
    return FakeResponse(
        status,
        {
            "hits": materialized,
            "nbHits": len(materialized) if nb_hits is None else nb_hits,
            "page": page,
            "hitsPerPage": hits_per_page,
            "nbPages": 1,
        },
        headers,
    )


def _iso_from(timestamp: Any) -> Any:
    """The `Z`-suffixed ISO spelling for a unix timestamp, when one is usable."""
    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")



class FakeHNClient:
    """A stand-in for `HackerNewsClient`, injected at the service's own seam.

    Records every call so a test can assert *which* windows were queried, how many
    trees were fetched and in what order -- the things the budgets and the refetch
    gate are actually about. Trees are addressed by id, and an id with no payload
    raises `SourceError` like a real failed request would, which is how the
    "one thread fails, the run finishes partial" case is set up.
    """

    def __init__(
        self,
        *,
        window_hits: Sequence[Mapping[str, Any]] = (),
        term_hits: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        items: Mapping[int, Mapping[str, Any]] | None = None,
        fail_items: Iterable[int] = (),
        window_error: Exception | None = None,
        nb_hits: int | None = None,
    ):
        self.window_hits = [dict(hit) for hit in window_hits]
        self.term_hits = {term: [dict(hit) for hit in hits] for term, hits in (term_hits or {}).items()}
        self.items = {int(key): dict(value) for key, value in (items or {}).items()}
        self.fail_items = {int(key) for key in fail_items}
        self.window_error = window_error
        self._nb_hits = nb_hits

        self.window_calls: list[tuple[int, int]] = []
        self.term_calls: list[str] = []
        self.term_filters: list[tuple[int, int]] = []
        self.item_calls: list[int] = []

    @staticmethod
    def _result(hits: list[dict[str, Any]], *, nb_hits: int | None = None) -> DiscoveryResult:
        return DiscoveryResult(
            hits=list(hits),
            pages_fetched=1 if hits else 0,
            nb_hits=len(hits) if nb_hits is None else nb_hits,
        )

    def search_window(self, *, start, end, min_points, min_comments) -> DiscoveryResult:
        if self.window_error is not None:
            raise self.window_error
        self.window_calls.append((int(start), int(end)))
        return self._result(self.window_hits, nb_hits=self._nb_hits)

    def search_term(
        self, *, term, since, min_points=0, min_comments=0, max_pages=1
    ) -> DiscoveryResult:
        self.term_calls.append(term)
        # Recorded so a test can assert the floor reaches the API rather than being
        # applied locally after the hits have already been transferred.
        self.term_filters.append((int(min_points), int(min_comments)))
        return self._result(self.term_hits.get(term, []))

    def fetch_item(self, hn_id: int) -> Mapping[str, Any]:
        self.item_calls.append(int(hn_id))
        if int(hn_id) in self.fail_items:
            raise SourceError(f"fake failure for item {hn_id}")
        if int(hn_id) not in self.items:
            raise SourceError(f"fake has no item {hn_id}")
        return self.items[int(hn_id)]
