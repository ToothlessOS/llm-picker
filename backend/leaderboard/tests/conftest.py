"""Shared fixtures for the leaderboard suite.

The cache backs the refresh lock. Redis is a deployment dependency, not a test
dependency, so it is swapped for in-process memory: what is under test is the
lock's *behaviour*, not the backend's.
"""

from __future__ import annotations

import pytest

LOCMEM_CACHE = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}


@pytest.fixture(autouse=True)
def _locmem_cache(settings):
    """Never let a test reach for Redis.

    Django re-instantiates `caches` when `CACHES` changes, so this is a real
    swap rather than an unused assignment. Cleared on both sides so a lock left
    held by a failing test cannot skip the next one.
    """
    from django.core.cache import cache

    settings.CACHES = LOCMEM_CACHE
    cache.clear()
    yield
    cache.clear()
