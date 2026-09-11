"""Test doubles for the two external boundaries.

Injected at *our* seams -- the `Transport` protocol and the `load_dataset`
callable -- rather than by patching `requests` or `datasets`. That means these
tests exercise our retry loop, our pagination and our error mapping, instead of
a library's interception machinery. It also means the suite never needs network
access and never imports `datasets`.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence

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
