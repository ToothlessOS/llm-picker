"""Inbound rate limiting for the read-only API.

Every endpoint here is `AllowAny` and unauthenticated by design, so the only
thing to count against is the client's IP. Two budgets are enforced on every
request -- a short *burst* ceiling that stops a runaway loop, and a *sustained*
daily ceiling that stops a patient scrape -- and both must pass.

**The limiter never fails a request it cannot count.** A cache backend that is
down raises `True` out of `allow_request` rather than propagating, because the
read path of this API otherwise needs no Redis at all: every response is served
from SQLite. Turning a cache outage into a 500 on every request would trade a
total outage for a lost rate limit, which is the wrong way round. The refresh
lock takes the same position for the same reason, degrading to "acquired" when
its backend is unreachable. Both log loudly, so the degraded state is visible
rather than silent.

**Nothing here is read at import time.** DRF binds
`APIView.throttle_classes = api_settings.DEFAULT_THROTTLE_CLASSES` when
`rest_framework.views` is first imported, and `SimpleRateThrottle` binds
`THROTTLE_RATES` the same way, so a setting consulted at import could never be
changed afterwards -- which would make `LEADERBOARD_THROTTLE_ENABLED` a lie and
the rates untestable. Both are therefore read per request, in `get_rate()`.

A malformed rate is a third failure mode. `parse_rate` runs inside the
constructor, which is *outside* `allow_request`'s guard, so `__init__` below
catches it too -- otherwise a `KeyError` would 500 every request. The
consequence of that catch is worth being explicit about: a typo'd rate leaves the
API **up and unlimited**, announced by one log line. That is a worse outcome than
a crash, which is why `leaderboard/checks.py` refuses to boot on it.
"""

from __future__ import annotations

import logging

from django.conf import settings
from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle

logger = logging.getLogger(__name__)

#: Namespaced so the throttle counters sit beside the refresh lock keys in
#: Redis, and are obvious in a `KEYS leaderboard:*`.
CACHE_KEY_TEMPLATE = "leaderboard:throttle:%(scope)s:%(ident)s"


def throttling_enabled() -> bool:
    """The master switch, read lazily -- see the module docstring."""
    return bool(getattr(settings, "LEADERBOARD_THROTTLE_ENABLED", True))


class LeaderboardThrottle(SimpleRateThrottle):
    """One budget, counted per client IP.

    Subclasses `SimpleRateThrottle` rather than DRF's `AnonRateThrottle`: the
    latter returns no cache key at all for an authenticated user, so the day
    this API grows an authenticated caller it would silently stop being
    throttled. The IP is the counter key here, full stop.

    `NUM_PROXIES` (settings) decides what "the client IP" means. It is set to 0
    deliberately: DRF's own default of `None` trusts `X-Forwarded-For` verbatim
    whenever the header is present, which would let any client mint a fresh
    bucket per request by sending a different fabricated value.
    """

    cache_format = CACHE_KEY_TEMPLATE
    scope: str = ""

    def get_rate(self) -> str | None:
        """Resolved per request. `None` makes DRF allow the request outright."""
        if not throttling_enabled():
            return None

        try:
            return api_settings.DEFAULT_THROTTLE_RATES[self.scope]
        except KeyError:
            logger.error(
                "No throttle rate configured for scope %r; requests are NOT rate "
                "limited. Set REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'][%r].",
                self.scope,
                self.scope,
            )
            return None

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }

    def __init__(self) -> None:
        try:
            super().__init__()
        except Exception:  # noqa: BLE001 -- an uncountable request is still served
            logger.error(
                "Throttle scope %r has an unparseable rate; requests are NOT rate "
                "limited. `manage.py check` reports the offending value.",
                self.scope,
                exc_info=True,
            )
            # `allow_request` short-circuits on a None rate, so this is the
            # fail-open path rather than a broken instance.
            self.rate = None
            self.num_requests, self.duration = None, None

    def allow_request(self, request, view) -> bool:
        try:
            return super().allow_request(request, view)
        except Exception:  # noqa: BLE001 -- see the module docstring
            logger.warning(
                "Throttle cache backend unavailable for scope %r; serving the "
                "request uncounted. Rate limiting is degraded until it recovers.",
                self.scope,
                exc_info=True,
            )
            return True


class BurstThrottle(LeaderboardThrottle):
    """Short-window ceiling: `LEADERBOARD_THROTTLE_BURST`, default 60/min."""

    scope = "burst"


class SustainedThrottle(LeaderboardThrottle):
    """Daily ceiling: `LEADERBOARD_THROTTLE_SUSTAINED`, default 2000/day."""

    scope = "sustained"
