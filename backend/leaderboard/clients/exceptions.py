"""Failures that originate outside our process.

Each carries a stable `code` that is written to `SyncRun.error_code`, so
troubleshooting a failed refresh never depends on parsing a message string.
"""

from __future__ import annotations


class SourceError(Exception):
    """Base class for anything that went wrong talking to an external provider."""

    #: Stable, machine-readable code persisted to SyncRun.error_code.
    code = "source_error"

    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class TransportError(SourceError):
    """Connection refused, DNS failure, read timeout -- never reached the app."""

    code = "transport_error"


class UpstreamServerError(SourceError):
    """5xx from the provider. Retried; if it persists, the run fails."""

    code = "upstream_server_error"


class AuthenticationError(SourceError):
    """401/403. Retrying would only burn quota, so this fails immediately."""

    code = "authentication_failed"


class RateLimitError(SourceError):
    """429, or a preflight check that the known quota is exhausted."""

    code = "rate_limit_exceeded"

    def __init__(self, message: str, *, retry_after: int | None = None, detail: dict | None = None):
        super().__init__(message, detail=detail)
        #: Seconds until the window resets, when the provider told us.
        self.retry_after = retry_after


class SchemaError(SourceError):
    """The payload parsed as JSON but did not match the shape we expect."""

    code = "schema_error"


class EmptyResponseError(SourceError):
    """A successful response that carried zero records.

    This is treated as a failure rather than an empty result, because the
    alternative -- believing it -- would blank the entire leaderboard from one
    bad response.
    """

    code = "empty_response"


class PaginationGuardError(SourceError):
    """The provider kept reporting `has_more` past our hard page ceiling."""

    code = "pagination_guard"
