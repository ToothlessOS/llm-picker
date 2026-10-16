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


# --------------------------------------------------------------------------- #
# Hacker News discussions
# --------------------------------------------------------------------------- #


@register()
def hackernews_settings_are_coherent(app_configs, **kwargs) -> list[Error | Warning]:
    """The Hacker News tunables have to agree with each other, not just parse.

    Every value here is a plausible number on its own, which is exactly why the
    relationships between them are what needs checking. Each failure below is
    silent in production:

    * `hits_per_page * max_page` above 1,000 would have Algolia return a
      *plausible truncated* set rather than an error, so the run's
      `window_truncated` flag would be the only hint that the window was not
      fully read.
    * `MAX_STORED_COMMENTS > MAX_COMMENTS` would put the truncation cap above the
      pre-flight refusal, so the cap could never bind.
    * `WINDOW_SLICE_DAYS > WINDOW_DAYS` would leave part of the retention window
      unqueried while the slices still looked exhaustive.
    * A negative floor would admit every story ever posted.

    Precedent is the throttle rates above: a configuration mistake that degrades
    a guarantee should refuse to boot rather than announce itself in a log line.
    """
    from .constants import HN_PAGINATION_CEILING, hn_config

    cfg = hn_config()
    errors: list[Error | Warning] = []

    def fail(message: str, hint: str, identifier: str) -> None:
        errors.append(Error(message, hint=hint, id=identifier))

    if cfg.window_days < 1:
        fail(
            f"LEADERBOARD_HN_WINDOW_DAYS is {cfg.window_days}.",
            "Retention is measured in days; use 1 or more.",
            "leaderboard.E006",
        )

    if cfg.window_slice_days < 1 or cfg.window_slice_days > cfg.window_days:
        fail(
            f"LEADERBOARD_HN_WINDOW_SLICE_DAYS is {cfg.window_slice_days}, outside "
            f"1..{cfg.window_days}.",
            (
                "The slice width must divide the retention window into the queries "
                "that read it. A slice wider than the window leaves days unqueried; "
                "one narrower than a day multiplies requests for nothing."
            ),
            "leaderboard.E007",
        )

    if cfg.hits_per_page < 1 or cfg.max_page < 1:
        fail(
            f"Hacker News pagination is degenerate: hits_per_page="
            f"{cfg.hits_per_page}, max_page={cfg.max_page}.",
            "Both must be at least 1.",
            "leaderboard.E008",
        )
    elif cfg.hits_per_page * cfg.max_page > HN_PAGINATION_CEILING:
        fail(
            f"LEADERBOARD_HN_HITS_PER_PAGE * LEADERBOARD_HN_MAX_PAGE is "
            f"{cfg.hits_per_page * cfg.max_page}, above Algolia's "
            f"{HN_PAGINATION_CEILING}-result ceiling.",
            (
                "Past that ceiling the search API returns a shorter list as though it "
                "were the whole result set, so a truncated window would look complete. "
                "Lower LEADERBOARD_HN_MAX_PAGE, or rely on the window slices."
            ),
            "leaderboard.E009",
        )

    if cfg.max_stored_comments < 1:
        fail(
            f"LEADERBOARD_HN_MAX_STORED_COMMENTS is {cfg.max_stored_comments}.",
            "The ingest cap must be at least 1, or no thread could ever store a comment.",
            "leaderboard.E010",
        )
    elif cfg.max_stored_comments > cfg.max_comments:
        fail(
            f"LEADERBOARD_HN_MAX_STORED_COMMENTS ({cfg.max_stored_comments}) exceeds "
            f"LEADERBOARD_HN_MAX_COMMENTS ({cfg.max_comments}).",
            (
                "The second is the pre-flight refusal, so a cap above it could never "
                "bind -- every thread would already have been refused before the "
                "truncation applied. Keep the stored cap at or below the refusal."
            ),
            "leaderboard.E011",
        )

    if cfg.min_points < 0 or cfg.min_comments < 0:
        fail(
            f"Hacker News floors are negative: points={cfg.min_points}, "
            f"comments={cfg.min_comments}.",
            "A negative floor would admit every story ever posted.",
            "leaderboard.E012",
        )

    if cfg.sweep_min_points < 0 or cfg.sweep_min_comments < 0:
        fail(
            f"Hacker News sweep floors are negative: points={cfg.sweep_min_points}, "
            f"comments={cfg.sweep_min_comments}.",
            "A negative floor would admit every story ever posted.",
            "leaderboard.E014",
        )
    elif (
        cfg.sweep_min_points > cfg.min_points
        or cfg.sweep_min_comments > cfg.min_comments
    ):
        # The sweep exists to reach what the window's floor excludes, so a sweep
        # floor above it makes the whole stream unable to find anything new --
        # while still spending its requests every hour.
        fail(
            "The Hacker News sweep floor is above the window floor: "
            f"sweep=({cfg.sweep_min_points}, {cfg.sweep_min_comments}) vs "
            f"window=({cfg.min_points}, {cfg.min_comments}).",
            (
                "The keyword sweep reaches threads *below* the window's floor, so "
                "raising it above that floor makes the sweep unable to find anything "
                "the window had not already found. Keep it lower -- it is also the "
                "bar a stored thread must clear to remain in the bank."
            ),
            "leaderboard.E015",
        )

    if cfg.keyword_query_budget < 0:
        fail(
            f"LEADERBOARD_HN_KEYWORD_QUERY_BUDGET is {cfg.keyword_query_budget}.",
            "Use 0 to disable the keyword sweep, or a positive number of queries per run.",
            "leaderboard.E013",
        )

    if cfg.max_trees_per_run < 1:
        errors.append(
            Warning(
                f"LEADERBOARD_HN_MAX_TREES_PER_RUN is {cfg.max_trees_per_run}, so no "
                "comment tree will ever be fetched.",
                hint="Set it to at least 1, or the bank will hold threads with no comments.",
                id="leaderboard.W002",
            )
        )

    return errors
