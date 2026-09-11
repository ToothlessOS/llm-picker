"""Non-blocking overlap protection for refresh runs.

A held lock means **skip**, never queue: a queued second refresh would fetch the
same data again for no benefit and spend a second slice of the shared AA quota.

This is the first of two layers. The second is the conditional unique index on
`SyncRun` (`source` where `status='running'`), which holds even when the cache is
unreachable -- so losing Redis degrades concurrency control, it does not remove
it.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import contextmanager
from typing import Iterator

from django.core.cache import cache

logger = logging.getLogger(__name__)

LOCK_KEY_TEMPLATE = "leaderboard:refresh:{source}"
DEFAULT_LOCK_TIMEOUT_SECONDS = 3600


def _acquire(key: str, token: str, timeout: int) -> bool:
    """`cache.add` is atomic for the backends we care about: it sets the key only
    if it does not already exist."""
    return bool(cache.add(key, token, timeout))


def _release(key: str, token: str) -> None:
    """Compare-and-delete: only the holder may release, so a slow run cannot
    delete a lock that a newer run has since taken."""
    try:
        if cache.get(key) == token:
            cache.delete(key)
    except Exception:  # noqa: BLE001 -- releasing must never mask the real error
        logger.warning("Failed to release refresh lock %s", key, exc_info=True)


@contextmanager
def run_lock(
    source: str,
    *,
    timeout: int = DEFAULT_LOCK_TIMEOUT_SECONDS,
    enabled: bool = True,
) -> Iterator[bool]:
    """Yield True when this process may proceed, False when another run holds it.

    If the cache backend is unavailable the lock degrades to "acquired" rather
    than failing the refresh outright -- the `SyncRun` constraint still prevents
    a genuine overlap, and losing a scheduled refresh to a cache outage would be
    the worse outcome.
    """
    if not enabled:
        yield True
        return

    key = LOCK_KEY_TEMPLATE.format(source=source)
    token = secrets.token_hex(16)

    try:
        acquired = _acquire(key, token, timeout)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Refresh lock backend unavailable for %s; falling back to the database "
            "constraint for overlap protection",
            source,
            exc_info=True,
        )
        yield True
        return

    if not acquired:
        yield False
        return

    try:
        yield True
    finally:
        _release(key, token)
