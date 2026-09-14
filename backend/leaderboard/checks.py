"""Boot-time validation, so a bad configuration fails at startup, not per request.

Registered from `LeaderboardConfig.ready()` -- **Django does not import an app's
`checks.py` for you**, whatever the convention suggests. Without that import this
module is dead code and every check below silently never runs; the tests in
`test_throttling.py` therefore drive `manage.py check` rather than calling these
functions, because the failure being guarded against is the registration, not the
validation.

That matters most for the throttle rates. DRF parses a rate inside the throttle's
constructor, and `api/throttling.py` wraps both that constructor and
`allow_request` so a cache or configuration failure degrades to *serving the
request uncounted* rather than to a 500. The upside is that the API stays up. The
downside is that a typo like `"sixty/min"` produces a public API with **no rate
limit at all**, announced by one log line among thousands. That is a worse failure
than a 500, and it is the one this module exists to convert into a refusal to
boot.

This mirrors the stance already taken on `CELERY_TIMEZONE`, where a bad value is
caught by the suite and by `manage.py check` rather than by beat failing silently
at 8am.
"""

from __future__ import annotations

from django.core.checks import Error, Warning, register
from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle

from .api.throttling import BurstThrottle, SustainedThrottle, throttling_enabled

#: The scopes every request is actually counted against. Read off the classes
#: themselves so a new throttle cannot be added without being validated here.
THROTTLE_CLASSES = (BurstThrottle, SustainedThrottle)

SETTING_HINT = "REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']"


def _parse_rate(rate: str):
    """DRF's own parser, on a throwaway instance.

    `parse_rate` touches no instance state, so calling it through the class is
    equivalent to constructing a throttle -- and validates the value with the
    exact code that will consume it, rather than a reimplementation that could
    drift. Note DRF matches the period by its **first letter** only, so
    `"60/mins"` is accepted as "60 per minute".
    """
    return SimpleRateThrottle.parse_rate(None, rate)


@register()
def throttle_rates_are_valid(app_configs, **kwargs):
    """Every rate DRF will parse must parse now."""
    if not throttling_enabled():
        return []

    rates = api_settings.DEFAULT_THROTTLE_RATES

    errors = []
    for throttle_class in THROTTLE_CLASSES:
        scope = throttle_class.scope
        if scope not in rates:
            errors.append(
                Error(
                    f"No throttle rate configured for scope {scope!r}.",
                    hint=(
                        f"Add it to {SETTING_HINT} in settings, or set "
                        "LEADERBOARD_THROTTLE_ENABLED=false to serve without limits."
                    ),
                    id="leaderboard.E001",
                )
            )
            continue

        rate = rates[scope]
        try:
            _parse_rate(rate)
        except (ValueError, KeyError, AttributeError):
            errors.append(
                Error(
                    f"Throttle rate for scope {scope!r} is not parseable: {rate!r}.",
                    hint=(
                        "Expected '<count>/<period>' with a period of s, m, h or d "
                        f"-- e.g. '60/min'. Set via {SETTING_HINT}, or "
                        "LEADERBOARD_THROTTLE_BURST / LEADERBOARD_THROTTLE_SUSTAINED."
                    ),
                    id="leaderboard.E002",
                )
            )

    return errors


@register()
def num_proxies_is_sane(app_configs, **kwargs):
    """`NUM_PROXIES` decides whether `X-Forwarded-For` is believed.

    Read through `api_settings` rather than out of `settings.REST_FRAMEWORK`
    directly, because the two disagree in exactly the case that matters: DRF's
    own default is `None`, so a `REST_FRAMEWORK` dict that simply omits the key
    passes `.get(..., 0)` while DRF starts trusting a header any client can write.
    The effective value is the only one worth validating.

    `None` is therefore an **error**, not an acceptable default -- it is the one
    value that silently disables the limit for anyone willing to set a header.
    """
    if not throttling_enabled():
        return []

    value = api_settings.NUM_PROXIES

    if value is None:
        return [
            Error(
                "NUM_PROXIES is unset, so X-Forwarded-For is trusted verbatim and "
                "any client can evade the rate limit by inventing an address.",
                hint=(
                    "Set DJANGO_NUM_PROXIES=0 to key on the socket peer, or to the "
                    "number of proxies you actually control."
                ),
                id="leaderboard.E003",
            )
        ]

    if isinstance(value, int):
        if value < 0:
            return [
                Error(
                    f"NUM_PROXIES is negative ({value}).",
                    hint="Use 0 to ignore X-Forwarded-For entirely.",
                    id="leaderboard.E004",
                )
            ]
        return []

    if isinstance(value, str) and value.strip().isdigit():
        # `env_int` already returns an int, so this is only reachable if the
        # setting was overridden directly; a warning is enough.
        return [
            Warning(
                f"NUM_PROXIES is the string {value!r} rather than an int.",
                hint="Set DJANGO_NUM_PROXIES to a number so DRF compares it as one.",
                id="leaderboard.W001",
            )
        ]

    return [
        Error(
            f"NUM_PROXIES is not an integer or None: {value!r}.",
            hint=(
                "0 means 'ignore X-Forwarded-For and use the socket peer', which is "
                "what you want unless you control the proxies in front of this app."
            ),
            id="leaderboard.E005",
        )
    ]
