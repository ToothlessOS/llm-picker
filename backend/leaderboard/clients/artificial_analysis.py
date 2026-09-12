"""Artificial Analysis API v2 client.

Wraps the single endpoint this project needs:

    GET https://artificialanalysis.ai/api/v2/language/models/free

Behaviour that matters, all of it driven by the local OpenAPI spec rather than
by assumption:

* Auth is the ``x-api-key`` header. The only query parameter is ``page``
  (1-indexed); there is no ``page_size`` -- the server decides that (200).
* Pagination is followed until ``has_more`` is false, under a hard page ceiling.
  AA reports ``has_more`` itself, but a bug that reports it forever would
  otherwise burn the shared 100-request/24h quota in a tight loop.
* ``X-RateLimit-*`` and ``X-AA-Tier`` are captured on **every** response,
  including failures, so a failed run still tells you how much quota is left.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping

from ..constants import AA_MAX_INLINE_RETRY_AFTER_SECONDS, AA_MAX_PAGES
from .exceptions import (
    AuthenticationError,
    EmptyResponseError,
    PaginationGuardError,
    RateLimitError,
    SchemaError,
    SourceError,
    TransportError,
    UpstreamServerError,
)
from .http import DEFAULT_TIMEOUT_SECONDS, RequestsTransport, Response, RetryPolicy, Transport

DEFAULT_BASE_URL = "https://artificialanalysis.ai/api/v2"
MODELS_FREE_PATH = "/language/models/free"


@dataclass(frozen=True)
class RateLimitSnapshot:
    """The most recent quota state AA reported."""

    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None
    tier: str = ""


@dataclass(frozen=True)
class AAFetchResult:
    """One complete, paginated read of the free-tier model list."""

    records: list[dict[str, Any]]
    pages_fetched: int
    page_size: int | None
    total_pages: int | None
    tier: str
    intelligence_index_version: float | None
    rate_limit: RateLimitSnapshot


def _header_lookup(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Case-insensitive header access that works for `requests` *and* for the
    plain dicts a test fake returns."""
    if not headers:
        return {}
    return {str(key).lower(): value for key, value in headers.items()}


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class ArtificialAnalysisClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        transport: Transport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        retry_policy: RetryPolicy | None = None,
        max_pages: int = AA_MAX_PAGES,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
    ):
        self._api_key = (api_key or "").strip()
        self._transport = transport if transport is not None else RequestsTransport()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retry_policy = retry_policy or RetryPolicy()
        self._max_pages = max_pages
        self._sleep = sleep
        self._uniform = uniform
        self._rate_limit = RateLimitSnapshot()
        self._pages_fetched = 0

    # -- introspection ----------------------------------------------------- #

    @property
    def configured(self) -> bool:
        """False when no API key is set. A missing key must never break the
        read-only API -- it only fails the AA refresh."""
        return bool(self._api_key)

    @property
    def last_rate_limit(self) -> RateLimitSnapshot:
        """Quota state from the most recent response, success or failure."""
        return self._rate_limit

    @property
    def pages_fetched(self) -> int:
        return self._pages_fetched

    # -- retrieval --------------------------------------------------------- #

    def fetch_all_models(self) -> AAFetchResult:
        """Read every page of `/language/models/free`.

        Raises rather than returning a partial list: a half-read catalogue would
        look like a mass model deletion to the deactivation pass.
        """
        if not self.configured:
            raise AuthenticationError(
                "AA_API_KEY is not configured; skipping Artificial Analysis refresh"
            )

        records: list[dict[str, Any]] = []
        page = 1
        page_size: int | None = None
        total_pages: int | None = None
        tier = ""
        index_version: float | None = None

        while True:
            if page > self._max_pages:
                raise PaginationGuardError(
                    f"AA still reported has_more after {self._max_pages} pages; aborting "
                    "rather than continuing to spend quota",
                    detail={"pages_fetched": self._pages_fetched, "max_pages": self._max_pages},
                )

            payload = self._get_page(page)
            self._pages_fetched += 1

            data = payload.get("data")
            if not isinstance(data, list):
                raise SchemaError(
                    f"AA page {page} has no `data` array",
                    detail={"page": page, "keys": sorted(map(str, payload.keys()))},
                )
            records.extend(entry for entry in data if isinstance(entry, Mapping))

            pagination = payload.get("pagination")
            if not isinstance(pagination, Mapping):
                raise SchemaError(
                    f"AA page {page} has no `pagination` object", detail={"page": page}
                )
            page_size = _as_int(pagination.get("page_size")) or page_size
            total_pages = _as_int(pagination.get("total_pages")) or total_pages
            tier = str(payload.get("tier") or tier or self._rate_limit.tier)
            version = payload.get("intelligence_index_version")
            if version is not None:
                try:
                    index_version = float(version)
                except (TypeError, ValueError):
                    index_version = index_version

            if not pagination.get("has_more"):
                break
            page += 1

        if not records:
            raise EmptyResponseError(
                "AA returned zero models; refusing to treat this as an empty catalogue",
                detail={"pages_fetched": self._pages_fetched},
            )

        return AAFetchResult(
            records=records,
            pages_fetched=self._pages_fetched,
            page_size=page_size,
            total_pages=total_pages,
            tier=tier,
            intelligence_index_version=index_version,
            rate_limit=self._rate_limit,
        )

    # -- internals --------------------------------------------------------- #

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key, "Accept": "application/json"}

    def _get_page(self, page: int) -> Mapping[str, Any]:
        url = f"{self._base_url}{MODELS_FREE_PATH}"
        attempts = self._retry_policy.max_attempts

        for attempt in range(1, attempts + 1):
            try:
                response = self._transport.get(
                    url,
                    headers=self._headers(),
                    params={"page": page},
                    timeout=self._timeout,
                )
            except TransportError:
                if attempt >= attempts:
                    raise
                self._sleep(self._retry_policy.delay_for(attempt, uniform=self._uniform))
                continue

            # Capture quota state before any status branching, so a 401 or a 429
            # still leaves us with the numbers we need to explain the failure.
            self._rate_limit = self._snapshot(response)
            status = response.status_code

            if 200 <= status < 300:
                return self._decode(response, page)

            if status == 429:
                retry_after = self._retry_after(response)
                if (
                    retry_after is not None
                    and retry_after <= AA_MAX_INLINE_RETRY_AFTER_SECONDS
                    and attempt < attempts
                ):
                    self._sleep(float(retry_after))
                    continue
                # A long window is not worth sleeping through inside a worker:
                # an honest failure lets the next scheduled run pick it up, and
                # the metadata endpoint can tell the frontend why.
                raise RateLimitError(
                    f"AA rate limit hit on page {page} (retry-after={retry_after})",
                    retry_after=retry_after,
                    detail={"page": page, "status": status},
                )

            if status in (401, 403):
                raise AuthenticationError(
                    f"AA rejected the API key (HTTP {status})",
                    detail={"page": page, "status": status},
                )

            if status >= 500:
                if attempt >= attempts:
                    raise UpstreamServerError(
                        f"AA returned HTTP {status} on page {page} after {attempt} attempts",
                        detail={"page": page, "status": status, "attempts": attempt},
                    )
                self._sleep(self._retry_policy.delay_for(attempt, uniform=self._uniform))
                continue

            # Any other 4xx is permanent; retrying cannot help.
            raise SourceError(
                f"AA returned HTTP {status} on page {page}",
                detail={"page": page, "status": status},
            )

        # Unreachable: every branch above either returns or raises.
        raise SourceError(f"AA page {page} exhausted its retry budget")

    def _decode(self, response: Response, page: int) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 -- any decode failure is the same to us
            raise SchemaError(
                f"AA returned a non-JSON body on page {page}",
                detail={"page": page, "exception": type(exc).__name__},
            ) from exc
        if not isinstance(payload, Mapping):
            raise SchemaError(
                f"AA page {page} body was {type(payload).__name__}, expected an object",
                detail={"page": page},
            )
        return payload

    def _snapshot(self, response: Response) -> RateLimitSnapshot:
        headers = _header_lookup(getattr(response, "headers", None))
        reset_raw = _as_int(headers.get("x-ratelimit-reset"))
        reset_at = (
            datetime.fromtimestamp(reset_raw, tz=timezone.utc) if reset_raw is not None else None
        )
        return RateLimitSnapshot(
            limit=_as_int(headers.get("x-ratelimit-limit")),
            remaining=_as_int(headers.get("x-ratelimit-remaining")),
            reset_at=reset_at,
            tier=str(headers.get("x-aa-tier") or ""),
        )

    @staticmethod
    def _retry_after(response: Response) -> int | None:
        """`Retry-After` is either delta-seconds or an HTTP-date."""
        raw = _header_lookup(getattr(response, "headers", None)).get("retry-after")
        if raw is None or raw == "":
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            pass
        try:
            when = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delta = (when - datetime.now(tz=timezone.utc)).total_seconds()
        return max(0, int(delta))
