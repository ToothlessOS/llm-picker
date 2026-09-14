"""The inbound rate limit.

Three properties are under test, and only the first is the obvious one:

* a client that exceeds its budget gets a 429, in the same envelope as every
  other error, with a `Retry-After` it can act on;
* **a client cannot escape the limit by lying about its address**, which is the
  whole reason `NUM_PROXIES` is pinned rather than left at DRF's default;
* **a client is never refused because the counter itself is broken.** The read
  path of this API needs no Redis at all, so a limiter that 500s when Redis is
  down would have turned a lost rate limit into a total outage.

The rates are overridden per test rather than exercised at their real values:
the default budget is 60 requests a minute, and a test that fired 61 requests at
every endpoint would be slow and would say nothing more than a small one does.
`get_rate()` is read per request precisely so this works -- see
`api/throttling.py`.
"""

from __future__ import annotations

import os

import pytest
from django.core.management import call_command

from leaderboard.api.throttling import (
    BurstThrottle,
    LeaderboardThrottle,
    SustainedThrottle,
)

BASE = "/api/v1/leaderboard"

PATHS = [
    "/overview/",
    "/categories/",
    "/categories/agent/",
    "/artificial-analysis/",
    "/models/claude-opus-5-high/",
    "/metadata/",
    "/unmatched/",
]

LIMIT = 3


@pytest.fixture
def limited(settings):
    """A three-request burst budget, so a test can exhaust it in four calls.

    Assigned as a whole new dict: pytest-django only fires `setting_changed`,
    and so only makes DRF reload `api_settings`, when the setting itself is
    reassigned. Mutating the existing dict in place would leave the override
    invisible.
    """
    rest_framework = dict(settings.REST_FRAMEWORK)
    rest_framework["DEFAULT_THROTTLE_RATES"] = {
        "burst": f"{LIMIT}/min",
        "sustained": "1000/day",
    }
    settings.REST_FRAMEWORK = rest_framework
    return LIMIT


def hit(client, path="/metadata/", **extra):
    return client.get(f"{BASE}{path}", **extra)


@pytest.mark.django_db
class TestTheLimit:
    def test_the_budget_is_spent_then_refused(self, client, limited, db):
        for _ in range(limited):
            assert hit(client).status_code == 200

        refused = hit(client)

        assert refused.status_code == 429

    def test_the_refusal_uses_the_established_error_envelope(self, client, limited, db):
        """A 429 that shipped DRF's bare `{"detail": ...}` while every other error
        carried an `error` string would be the one status the frontend cannot
        branch on."""
        for _ in range(limited):
            hit(client)

        body = hit(client).json()

        assert body["error"] == "throttled"
        assert "detail" in body

    def test_the_detail_is_nested_because_drf_raises_a_plain_detail(self, client, limited, db):
        """Pinned to what the wire actually carries.

        `Throttled` is raised with a string `detail`, and the exception handler
        preserves DRF's own shape under a `detail` key -- so the message ends up
        one level deeper than every other error's. Asserting only that a `detail`
        key exists passes on both shapes and documents neither.
        """
        for _ in range(limited):
            hit(client)

        body = hit(client).json()

        assert isinstance(body["detail"], dict)
        assert "throttled" in body["detail"]["detail"].lower()

    def test_the_refusal_says_how_long_to_wait(self, client, limited, db):
        """Without `Retry-After` a client can only guess -- and the guess that
        matters is whether to wait or give up."""
        for _ in range(limited):
            hit(client)

        refused = hit(client)

        assert int(refused.headers["Retry-After"]) > 0

    def test_the_budget_is_per_client_not_global(self, client, limited, db, settings):
        """Two callers must not share one bucket, or the first noisy client locks
        everyone else out."""
        rest_framework = dict(settings.REST_FRAMEWORK)
        rest_framework["NUM_PROXIES"] = 1
        settings.REST_FRAMEWORK = rest_framework

        for _ in range(limited):
            assert hit(client, HTTP_X_FORWARDED_FOR="1.1.1.1").status_code == 200

        assert hit(client, HTTP_X_FORWARDED_FOR="2.2.2.2").status_code == 200
        assert hit(client, HTTP_X_FORWARDED_FOR="1.1.1.1").status_code == 429


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_every_endpoint_is_counted(client, limited, db, path):
    for _ in range(limited):
        hit(client, path)

    assert hit(client, path).status_code == 429, f"{path} is not rate limited"


@pytest.mark.django_db
class TestWhatIsCounted:
    """`OPTIONS` and `HEAD` are easy to assume are free. Only one `OPTIONS` is."""

    def test_a_cors_preflight_is_free(self, client, limited, db):
        """The middleware answers it before a view runs, so it never reaches the
        throttle -- which is what keeps a browser's preflight from spending the
        budget the actual request needs."""
        for _ in range(limited * 3):
            response = client.options(
                f"{BASE}/metadata/",
                HTTP_ORIGIN="http://localhost:5173",
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            )
            assert response.status_code == 200

    def test_a_bare_options_is_counted(self, client, limited, db):
        """No `Access-Control-Request-Method`, so it is not a preflight and the
        view handles it like any other method."""
        for _ in range(limited):
            hit(client)

        assert client.options(f"{BASE}/metadata/").status_code == 429

    def test_a_head_is_counted(self, client, limited, db):
        """`HEAD` is in `http_method_names` alongside `GET`. An uptime monitor
        polling with it spends the same budget as a browser."""
        for _ in range(limited):
            hit(client)

        assert client.head(f"{BASE}/metadata/").status_code == 429


@pytest.mark.django_db
class TestAddressTrust:
    """`X-Forwarded-For` is a request header, so anyone can send it.

    Believing it without a proxy in front means the limit is opt-in: a client
    mints a new identity per request and is never counted. DRF's own default
    (`NUM_PROXIES = None`) does exactly that, which is why settings pins it.
    """

    def test_a_spoofed_address_does_not_buy_a_fresh_budget(self, client, limited, db):
        for index in range(limited):
            hit(client, HTTP_X_FORWARDED_FOR=f"10.0.0.{index}")

        spoofed = hit(client, HTTP_X_FORWARDED_FOR="10.0.0.99")

        assert spoofed.status_code == 429

    def test_the_header_is_believed_once_proxies_are_declared(self, client, limited, db, settings):
        """The deployment path: behind a proxy the header is the only place the
        real client address exists, so `NUM_PROXIES` makes it authoritative."""
        rest_framework = dict(settings.REST_FRAMEWORK)
        rest_framework["NUM_PROXIES"] = 1
        settings.REST_FRAMEWORK = rest_framework

        for _ in range(limited):
            hit(client, HTTP_X_FORWARDED_FOR="10.0.0.1")

        assert hit(client, HTTP_X_FORWARDED_FOR="10.0.0.2").status_code == 200


@pytest.mark.django_db
class TestItNeverFailsARequest:
    def test_a_cache_outage_serves_the_request_uncounted(
        self, client, monkeypatch, limited, db, caplog
    ):
        """The counter lives in Redis; the data does not. Losing the counter must
        cost the rate limit, never the API."""

        class Unreachable:
            def get(self, *args, **kwargs):
                raise ConnectionError("redis is down")

            def set(self, *args, **kwargs):
                raise ConnectionError("redis is down")

            def add(self, *args, **kwargs):
                raise ConnectionError("redis is down")

        monkeypatch.setattr(LeaderboardThrottle, "cache", Unreachable())

        with caplog.at_level("WARNING", logger="leaderboard.api.throttling"):
            for _ in range(limited * 3):
                assert hit(client).status_code == 200

        # Asserted explicitly: without it this test would also pass if the
        # throttle had simply never consulted the cache, which is the opposite
        # of what it claims to prove.
        assert "cache backend unavailable" in caplog.text

    def test_the_kill_switch_serves_without_counting(self, client, limited, db, settings):
        settings.LEADERBOARD_THROTTLE_ENABLED = False

        for _ in range(limited * 3):
            assert hit(client).status_code == 200


@pytest.mark.django_db
class TestConfigurationFailsAtBoot:
    """A rate is parsed inside the throttle's constructor, *outside* the fail-open
    guard, so an unparseable one is a 500 on every request. It has to be caught
    before a request is ever served."""

    def test_the_shipped_configuration_is_valid(self):
        call_command("check")

    def test_a_bad_rate_stops_the_boot(self, settings):
        from django.core.management.base import SystemCheckError

        rest_framework = dict(settings.REST_FRAMEWORK)
        rest_framework["DEFAULT_THROTTLE_RATES"] = {"burst": "sixty/min", "sustained": "2000/day"}
        settings.REST_FRAMEWORK = rest_framework

        with pytest.raises(SystemCheckError, match="leaderboard.E002"):
            call_command("check")

    def test_the_check_is_registered_at_a_real_boot(self):
        """Run in a **subprocess**, which is the only way this can fail honestly.

        Django does not import an app's `checks.py` for you -- an app registers
        its checks from `ready()`. This module imports `leaderboard.checks`
        directly (to unit-test the functions), and that import registers them for
        the rest of the session, so an in-process `manage.py check` here would
        pass whether or not `ready()` does its job. A fresh interpreter is the
        only observer that has not already been contaminated.

        This is not hypothetical: the check was initially written on the
        assumption that Django auto-discovers `checks.py`, and the entire module
        was dead code until this test was added.
        """
        import subprocess
        import sys

        from django.conf import settings as django_settings

        environment = {**os.environ, "LEADERBOARD_THROTTLE_BURST": "sixty/min"}

        completed = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=django_settings.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
        )

        assert completed.returncode != 0, (
            "a malformed throttle rate booted cleanly, so `leaderboard/checks.py` "
            "is not registered -- check the import in LeaderboardConfig.ready()"
        )
        assert "leaderboard.E002" in completed.stderr

    def test_an_unparseable_rate_is_an_error(self, settings):
        from leaderboard.checks import throttle_rates_are_valid

        rest_framework = dict(settings.REST_FRAMEWORK)
        rest_framework["DEFAULT_THROTTLE_RATES"] = {"burst": "sixty/min", "sustained": "2000/day"}
        settings.REST_FRAMEWORK = rest_framework

        errors = throttle_rates_are_valid(None)

        assert [error.id for error in errors] == ["leaderboard.E002"]

    def test_a_missing_scope_is_an_error(self, settings):
        from leaderboard.checks import throttle_rates_are_valid

        rest_framework = dict(settings.REST_FRAMEWORK)
        rest_framework["DEFAULT_THROTTLE_RATES"] = {"burst": "60/min"}
        settings.REST_FRAMEWORK = rest_framework

        errors = throttle_rates_are_valid(None)

        assert [error.id for error in errors] == ["leaderboard.E001"]

    def test_a_disabled_limiter_is_not_checked(self, settings):
        """With the limiter off there is no rate to get wrong."""
        from leaderboard.checks import throttle_rates_are_valid

        settings.LEADERBOARD_THROTTLE_ENABLED = False
        rest_framework = dict(settings.REST_FRAMEWORK)
        rest_framework["DEFAULT_THROTTLE_RATES"] = {"burst": "sixty/min"}
        settings.REST_FRAMEWORK = rest_framework

        assert throttle_rates_are_valid(None) == []


@pytest.mark.django_db
class TestProxyConfiguration:
    def test_an_unset_num_proxies_is_an_error_not_a_default(self, settings):
        """DRF's own default is `None`, under which `get_ident` believes
        `X-Forwarded-For` verbatim. The check must read the *effective* value:
        reading `settings.REST_FRAMEWORK.get(..., 0)` would substitute a safe
        default for an unsafe reality, and stay silent about it."""
        from leaderboard.checks import num_proxies_is_sane

        rest_framework = dict(settings.REST_FRAMEWORK)
        rest_framework.pop("NUM_PROXIES", None)
        settings.REST_FRAMEWORK = rest_framework

        errors = num_proxies_is_sane(None)

        assert [error.id for error in errors] == ["leaderboard.E003"]

    def test_retry_after_is_readable_from_a_browser(self):
        """`Retry-After` is not CORS-safelisted, so without an explicit
        `Access-Control-Expose-Headers` the frontend receives the 429 and cannot
        read how long to wait -- the one thing the error carries."""
        from django.conf import settings as django_settings

        assert "Retry-After" in django_settings.CORS_EXPOSE_HEADERS


class TestWiring:
    def test_both_budgets_are_installed_on_every_view(self):
        """The classes are registered globally rather than per view, so a new
        endpoint inherits them by default. This asserts that is still true."""
        from django.conf import settings as django_settings

        from leaderboard.api.views import LeaderboardView

        configured = django_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"]

        assert "leaderboard.api.throttling.BurstThrottle" in configured
        assert "leaderboard.api.throttling.SustainedThrottle" in configured

        # DRF resolves the dotted paths to classes once, when `APIView` is
        # defined, so the view holds the classes rather than the strings.
        assert LeaderboardView.throttle_classes == [BurstThrottle, SustainedThrottle]

    def test_the_two_classes_count_separately(self):
        """Same client, two budgets: they must not share a cache key, or the
        daily limit would be spent by the minute one."""
        assert BurstThrottle.scope != SustainedThrottle.scope

    def test_the_defaults_are_the_agreed_budgets(self):
        from django.conf import settings as django_settings

        rates = django_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]

        assert rates["burst"] == "60/min"
        assert rates["sustained"] == "2000/day"

    def test_num_proxies_does_not_trust_the_header_by_default(self):
        """DRF's default of `None` believes `X-Forwarded-For` unconditionally.
        Shipping that would be a silent hole rather than a visible one."""
        from django.conf import settings as django_settings

        assert django_settings.REST_FRAMEWORK["NUM_PROXIES"] == 0
