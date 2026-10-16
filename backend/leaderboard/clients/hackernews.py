"""Hacker News client, over the Algolia search API.

Two read paths, and the reason both live here:

* **Discovery** -- `GET /search_by_date`, filtered server-side with
  `numericFilters` on `created_at_i`, `points` and `num_comments`, so finding the
  notable stories of a window costs a handful of requests rather than one request
  per story.
* **Trees** -- `GET /items/{id}`, which returns a story's **entire nested comment
  tree in one response**.

The official Firebase API is deliberately not used. It offers no auth advantage
(neither API needs a key), its `topstories.json` carries no metadata -- so
filtering by points means fetching 500 items to look at them -- and building one
comment tree there costs *one request per comment*: roughly 361 for a 360-comment
thread, against **1** here. A second source would buy a second error taxonomy, a
second fake and a second drift surface, and no capability.

Three guards, each for a documented property of this API:

1. **The 1,000-result ceiling.** ``hitsPerPage * page`` cannot exceed 1,000, and
   past it the API returns a *plausible-looking truncated set* rather than an
   error -- a silently wrong answer. Requesting a page beyond the ceiling raises
   `PaginationGuardError`; the discovery window is sliced so this is never
   reached in practice, and `checks.py` validates the arithmetic at boot.
2. **Enormous payloads.** A thousand-comment thread is megabytes of JSON, so
   `Content-Length` is checked *before* the body is read.
3. **Unknown page counts.** `nbHits` is reported honestly and compared against
   what was actually collected, so truncation is a recorded fact rather than an
   assumption.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from ..constants import HN_PAGINATION_CEILING
from .exceptions import (
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
from .http import (
    DEFAULT_TIMEOUT_SECONDS,
    RequestsTransport,
    Response,
    RetryPolicy,
    Transport,
    header_lookup,
    retry_after_seconds,
)

DEFAULT_BASE_URL = "https://hn.algolia.com/api/v1"
SEARCH_BY_DATE_PATH = "/search_by_date"
ITEMS_PATH = "/items"

#: Identifies this project to a free public API. Algolia does not require it, and
#: an anonymous client is the kind that gets throttled first.
USER_AGENT = "llm-picker/0.1 (+https://github.com/ToothlessOS/llm-picker)"


class _TransportFactory(Protocol):
    def __call__(self) -> Transport: ...


def _default_transport() -> Transport:
    """The production transport.

    A named function rather than an inline `RequestsTransport()` so the
    no-network test can replace this one seam and see a failure naming our code
    rather than a socket call -- the same reason `lmarena._default_loader` exists.
    """
    return RequestsTransport()


@dataclass(frozen=True)
class DiscoveryResult:
    """One paginated sweep of the search endpoint."""

    hits: list[dict[str, Any]] = field(default_factory=list)
    pages_fetched: int = 0
    #: What the API said the *total* match count was, which can exceed what it
    #: will ever hand back.
    nb_hits: int = 0

    @property
    def truncated(self) -> bool:
        """True when we collected fewer hits than the API reported.

        Recorded rather than inferred: a caller that saw only part of a window
        must not report a top-10 as though it had seen everything.
        """
        return len(self.hits) < self.nb_hits


class HackerNewsClient:
    def __init__(
        self,
        *,
        transport: Transport | None = None,
        transport_factory: _TransportFactory | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        tree_timeout: float = 45.0,
        retry_policy: RetryPolicy | None = None,
        hits_per_page: int = 100,
        max_page: int = 9,
        max_item_bytes: int = 8_000_000,
        max_inline_retry_after_seconds: int = 60,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
    ):
        self._transport = (
            transport
            if transport is not None
            else (transport_factory or _default_transport)()
        )
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        #: Comment trees are far larger than search responses, so they get their
        #: own ceiling: a search page timing out after 30s is a problem, but a
        #: 600-comment tree legitimately needs longer to arrive.
        self._tree_timeout = tree_timeout
        self._retry_policy = retry_policy or RetryPolicy()
        self._hits_per_page = hits_per_page
        self._max_page = max_page
        self._max_item_bytes = max_item_bytes
        self._max_inline_retry_after = max_inline_retry_after_seconds
        self._sleep = sleep
        self._uniform = uniform
        self._requests_made = 0

    # -- introspection ----------------------------------------------------- #

    @property
    def requests_made(self) -> int:
        """HTTP requests spent, for the run summary.

        Nothing here needs a key, so this is the only cost the run has to report.
        """
        return self._requests_made

    @property
    def max_pages_within_ceiling(self) -> int:
        """How many pages this configuration may fetch before the API's ceiling."""
        return max(1, HN_PAGINATION_CEILING // self._hits_per_page)

    # -- discovery --------------------------------------------------------- #

    def search_window(
        self,
        *,
        start: int,
        end: int,
        min_points: int,
        min_comments: int,
        max_pages: int | None = None,
    ) -> DiscoveryResult:
        """Every story posted in ``(start, end]`` above the points/comments floor.

        The floor is applied *server-side* through `numericFilters`, which is what
        makes a window affordable: the alternative is fetching every story of the
        period and discarding almost all of them.
        """
        numeric = ",".join(
            [
                f"created_at_i>{int(start)}",
                f"created_at_i<{int(end)}",
                f"points>={int(min_points)}",
                f"num_comments>={int(min_comments)}",
            ]
        )
        result = self._paginate(query=None, numeric_filters=numeric, max_pages=max_pages)

        if not result.hits:
            # A window with *no* qualifying stories is not a quiet period, it is a
            # broken query: Hacker News always has hundreds of stories above the
            # floor in a week, so zero means the filters stopped meaning what we
            # think. Failing keeps discovery from silently emptying the bank.
            #
            # Only the window query gets this treatment. A single term matching
            # nothing is the ordinary case -- see `search_term`.
            raise EmptyResponseError(
                "Hacker News window query returned no stories; refusing to treat "
                "this as a quiet period",
                detail={
                    "start": int(start),
                    "end": int(end),
                    "min_points": int(min_points),
                    "min_comments": int(min_comments),
                    "pages_fetched": result.pages_fetched,
                },
            )
        return result

    def search_term(
        self,
        *,
        term: str,
        since: int,
        min_points: int = 0,
        min_comments: int = 0,
        max_pages: int = 1,
    ) -> DiscoveryResult:
        """Stories matching ``term`` since ``since``, above a *lower* floor.

        The coverage hedge: it reaches a genuinely relevant thread that sits below
        the points floor the window query needs. The floor here is deliberately
        lower than the window's rather than absent -- "below the top stories of the
        week" and "trivia" are different thresholds, and a sweep with no floor at
        all drags in threads with two points and three comments.

        A term that matches nothing is the normal case and **not** an error --
        only the window query treats an empty result as a failure.
        """
        numeric = ",".join(
            [
                f"created_at_i>{int(since)}",
                f"points>={int(min_points)}",
                f"num_comments>={int(min_comments)}",
            ]
        )
        return self._paginate(query=term, numeric_filters=numeric, max_pages=max_pages)

    def fetch_item(self, hn_id: int) -> Mapping[str, Any]:
        """One story with its whole nested comment tree."""
        payload = self._get(
            f"{ITEMS_PATH}/{int(hn_id)}",
            params=None,
            timeout=self._tree_timeout,
            context=f"item {hn_id}",
        )
        return payload

    # -- internals --------------------------------------------------------- #

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "User-Agent": USER_AGENT}

    def _paginate(
        self,
        *,
        query: str | None,
        numeric_filters: str,
        max_pages: int | None,
    ) -> DiscoveryResult:
        limit = self._max_page if max_pages is None else max_pages
        hits: list[dict[str, Any]] = []
        nb_hits = 0
        pages_fetched = 0
        page = 0

        while pages_fetched < limit:
            self._guard_ceiling(page)

            params: dict[str, Any] = {
                "tags": "story",
                "numericFilters": numeric_filters,
                "hitsPerPage": self._hits_per_page,
                "page": page,
            }
            if query:
                params["query"] = query

            payload = self._get(
                SEARCH_BY_DATE_PATH, params=params, timeout=self._timeout, context=f"search page {page}"
            )
            pages_fetched += 1

            page_hits = payload.get("hits")
            if not isinstance(page_hits, list):
                raise SchemaError(
                    f"Hacker News search page {page} has no `hits` array",
                    detail={"page": page, "keys": sorted(map(str, payload.keys()))},
                )
            hits.extend(entry for entry in page_hits if isinstance(entry, Mapping))

            reported = _as_int(payload.get("nbHits"))
            if reported is not None:
                nb_hits = max(nb_hits, reported)

            page += 1
            if not page_hits:
                break
            nb_pages = _as_int(payload.get("nbPages"))
            if nb_pages is not None and page >= nb_pages:
                break

        return DiscoveryResult(hits=hits, pages_fetched=pages_fetched, nb_hits=nb_hits)

    def _guard_ceiling(self, page: int) -> None:
        """Refuse a page the API cannot serve honestly.

        Past 1,000 results Algolia returns a shorter list *as though it were the
        whole thing*, so a caller cannot tell truncation from a small result set.
        Failing here is the only way to keep "we saw everything above the floor"
        meaning what it says.
        """
        if page >= self.max_pages_within_ceiling:
            raise PaginationGuardError(
                f"Hacker News search cannot page past {HN_PAGINATION_CEILING} results "
                f"({self._hits_per_page} per page); refusing to request page {page}",
                detail={
                    "page": page,
                    "hits_per_page": self._hits_per_page,
                    "ceiling": HN_PAGINATION_CEILING,
                },
            )

    def _get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        timeout: float,
        context: str,
    ) -> Mapping[str, Any]:
        url = f"{self._base_url}{path}"
        attempts = self._retry_policy.max_attempts

        for attempt in range(1, attempts + 1):
            try:
                response = self._transport.get(
                    url, headers=self._headers(), params=params, timeout=timeout
                )
            except TransportError:
                if attempt >= attempts:
                    raise
                self._sleep(self._retry_policy.delay_for(attempt, uniform=self._uniform))
                continue

            self._requests_made += 1
            status = response.status_code

            if 200 <= status < 300:
                self._guard_size(response, context)
                return self._decode(response, context)

            if status == 429:
                retry_after = retry_after_seconds(response)
                if (
                    retry_after is not None
                    and retry_after <= self._max_inline_retry_after
                    and attempt < attempts
                ):
                    self._sleep(float(retry_after))
                    continue
                # A long window is not worth sleeping through inside a worker:
                # an honest failure lets the next hourly run pick it up.
                raise RateLimitError(
                    f"Hacker News rate limit hit on {context} (retry-after={retry_after})",
                    retry_after=retry_after,
                    detail={"context": context, "status": status},
                )

            if status in (401, 403):
                # The search API needs no key, so this is a block rather than a
                # credential problem -- and retrying a block only deepens it.
                raise AuthenticationError(
                    f"Hacker News refused the request (HTTP {status}) on {context}",
                    detail={"context": context, "status": status},
                )

            if status >= 500:
                if attempt >= attempts:
                    raise UpstreamServerError(
                        f"Hacker News returned HTTP {status} on {context} after "
                        f"{attempt} attempts",
                        detail={"context": context, "status": status, "attempts": attempt},
                    )
                self._sleep(self._retry_policy.delay_for(attempt, uniform=self._uniform))
                continue

            # Any other 4xx is permanent; retrying cannot help.
            raise SourceError(
                f"Hacker News returned HTTP {status} on {context}",
                detail={"context": context, "status": status},
            )

        # Unreachable: every branch above either returns or raises.
        raise SourceError(f"Hacker News request for {context} exhausted its retry budget")

    def _guard_size(self, response: Response, context: str) -> None:
        """Refuse an oversized body before reading it.

        `Content-Length` is absent on a chunked response, in which case this
        cannot help and the ingest-side comment cap is what bounds the result --
        hence two guards rather than one.
        """
        length = _as_int(header_lookup(getattr(response, "headers", None)).get("content-length"))
        if length is not None and length > self._max_item_bytes:
            raise PayloadTooLargeError(
                f"Hacker News response for {context} is {length} bytes, over the "
                f"{self._max_item_bytes}-byte ceiling",
                detail={
                    "context": context,
                    "content_length": length,
                    "max_item_bytes": self._max_item_bytes,
                },
            )

    def _decode(self, response: Response, context: str) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 -- any decode failure is the same to us
            raise SchemaError(
                f"Hacker News returned a non-JSON body for {context}",
                detail={"context": context, "exception": type(exc).__name__},
            ) from exc
        if not isinstance(payload, Mapping):
            raise SchemaError(
                f"Hacker News body for {context} was {type(payload).__name__}, "
                "expected an object",
                detail={"context": context},
            )
        return payload


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


__all__ = [
    "DEFAULT_BASE_URL",
    "DiscoveryResult",
    "HackerNewsClient",
    "ITEMS_PATH",
    "SEARCH_BY_DATE_PATH",
    "USER_AGENT",
]
