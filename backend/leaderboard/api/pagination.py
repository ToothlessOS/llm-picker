"""Pagination, and the `meta` block that rides along with every page.

`meta` is attached to *every* page rather than only to `/metadata/`, because the
frontend needs to render a "data as of ..." badge next to the table it is
already showing. Making it a second request would let the badge and the rows
disagree.
"""

from __future__ import annotations

from typing import Any, Mapping

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from ..constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .errors import InvalidParameter


class LeaderboardPagination(PageNumberPagination):
    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE

    def __init__(self) -> None:
        super().__init__()
        #: Set by the view between `paginate_queryset` and
        #: `get_paginated_response`. A plain attribute rather than a hook,
        #: because the content depends on what the view just queried.
        self.extra_meta: Mapping[str, Any] = {}

    def get_page_size(self, request) -> int:
        raw = request.query_params.get(self.page_size_query_param)
        if raw is None or raw.strip() == "":
            return self.page_size
        try:
            value = int(raw.strip())
        except (TypeError, ValueError):
            raise InvalidParameter(
                self.page_size_query_param,
                f"{self.page_size_query_param} must be an integer, got {raw!r}.",
            ) from None
        if value < 1:
            raise InvalidParameter(
                self.page_size_query_param,
                f"{self.page_size_query_param} must be at least 1, got {value}.",
            )
        # Clamped, not rejected: asking for more than the cap is a reasonable
        # thing for a client to do, and silently honouring it is what would be
        # unreasonable. `page_size` echoes back what was actually used.
        return min(value, self.max_page_size)

    def get_paginated_response(self, data) -> Response:
        return Response(
            {
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "page_size": self.page.paginator.per_page,
                "results": data,
                "meta": dict(self.extra_meta),
            }
        )
