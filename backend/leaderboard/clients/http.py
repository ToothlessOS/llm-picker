"""HTTP transport seam and the retry policy that sits on top of it.

The transport is a two-method protocol rather than a monkey-patched `requests`,
so tests inject a fake and assert on *our* retry loop instead of re-testing the
library's. `RequestsTransport` is configured with `max_retries=0` for the same
reason: all retry behaviour must live in code we can read and test.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

import requests

from .exceptions import TransportError

DEFAULT_TIMEOUT_SECONDS: float = 30.0


@runtime_checkable
class Response(Protocol):
    """The slice of `requests.Response` the clients actually use."""

    status_code: int
    headers: Mapping[str, str]

    def json(self) -> Any: ...


@runtime_checkable
class Transport(Protocol):
    """Everything the clients need from the network, and nothing more."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> Response: ...


class RequestsTransport:
    """The production transport.

    Contract: return a `Response` for *any* HTTP status, and raise
    `TransportError` only when no response was received at all. Status-code
    policy belongs to the client, not here.
    """

    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=0)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> Response:
        try:
            return self._session.get(url, headers=dict(headers), params=params, timeout=timeout)
        except requests.RequestException as exc:
            raise TransportError(
                f"{type(exc).__name__} calling {url}: {exc}",
                detail={"url": url, "exception": type(exc).__name__},
            ) from exc

    def close(self) -> None:
        self._session.close()


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with full jitter, capped.

    Applied to connection failures, timeouts and 5xx only. 4xx responses are
    permanent by construction -- a retry storm against a 401 would consume the
    whole daily quota for no possible benefit.
    """

    max_attempts: int = 4
    base_delay: float = 1.0
    max_delay: float = 30.0

    def delay_for(self, attempt: int, *, uniform: Any = random.uniform) -> float:
        """Seconds to wait after `attempt` (1-indexed) has failed."""
        ceiling = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        # Full jitter: spreads a fleet of workers out after a shared outage
        # instead of having them all retry on the same tick.
        return float(uniform(0, ceiling))
