"""App configuration.

Turns on SQLite's write-ahead log so the Celery worker can write while
`runserver` is reading the same database file. Without it a reader can observe a
half-written refresh -- at 535 webdev rows that is a real window, not a
theoretical one, and the API would serve a board that is half old and half new.

The pragma is applied from the `connection_created` signal rather than from
`ready()`. Two reasons: `ready()` runs before the app registry is populated, so
touching the database there raises Django's own "accessing the database during
app initialization is discouraged" warning; and a signal handler re-applies it
per connection, which is what actually matters -- the Celery worker and the web
process are separate processes with separate connections, and a pragma set once
at import time only covers whichever one imported first.
"""

from django.apps import AppConfig
from django.db.backends.signals import connection_created
from django.dispatch import receiver


@receiver(connection_created, dispatch_uid="leaderboard.enable_sqlite_wal")
def _enable_sqlite_wal(sender, connection, **kwargs) -> None:
    """Best-effort WAL switch.

    Never fatal: a read-only database, a locked file, or a test run against an
    in-memory database must all still boot. Losing the pragma costs concurrency,
    not correctness.
    """
    if connection.vendor != "sqlite":
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
    except Exception:  # noqa: BLE001 -- see the docstring
        pass


class LeaderboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "leaderboard"
    verbose_name = "Leaderboard"

    def ready(self) -> None:
        """Register the system checks.

        Django does **not** discover an app's `checks.py` on its own, despite the
        convention -- an app has to import it, and `ready()` is the documented
        place. Imported for the side effect only; the module registers itself
        with `@register()` on import.

        This is not the database work the module docstring above rules out for
        `ready()`: it imports settings-reading code and nothing else, so the app
        registry is still free of database access at this point.
        """
        from . import checks  # noqa: F401 -- imported for its registration side effect
