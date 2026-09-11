"""External data retrieval.

Nothing in this package writes to the database, and nothing outside it performs
network I/O. Each client is constructed with its transport/loader injected, so
the whole retry and pagination surface is testable without patching a library.
"""

from .artificial_analysis import ArtificialAnalysisClient, AAFetchResult, RateLimitSnapshot
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
from .http import RequestsTransport, Response, Transport
from .lmarena import LMArenaClient, LoadedSplit

__all__ = [
    "AAFetchResult",
    "ArtificialAnalysisClient",
    "AuthenticationError",
    "EmptyResponseError",
    "LMArenaClient",
    "LoadedSplit",
    "PaginationGuardError",
    "RateLimitError",
    "RateLimitSnapshot",
    "RequestsTransport",
    "Response",
    "SchemaError",
    "SourceError",
    "Transport",
    "TransportError",
    "UpstreamServerError",
]
