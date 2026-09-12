"""The error envelope.

Every error response carries an `error` string, so the frontend can branch on
*what kind* of failure it got rather than parsing prose. DRF's own shapes are
preserved underneath a `detail` key for 404/405/parser errors -- there is no
value in re-inventing them, and the frontend gets the familiar `detail` field it
would expect from any DRF service.

Two shapes are worth knowing about:

* ``invalid_parameter`` -- a query parameter was malformed or not in the
  whitelist. Carries `param` and, where a whitelist exists, `allowed`, so the
  frontend can render "order by one of: ..." without hard-coding the list.
* ``model_incomplete`` -- a 404 that is *not* an error to escalate. The model
  exists; it simply has no counterpart in the other source, so it is excluded
  from the joined endpoints by the completeness rule. The body says which model
  and why, so a dead link explains itself.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler

#: Status code -> the `error` string used when DRF raised the exception itself.
_DEFAULT_CODES = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    415: "unsupported_media_type",
    429: "throttled",
    500: "server_error",
}


class StructuredDetail:
    """An `APIException` whose `detail` is *data* rather than a message.

    DRF runs every scalar leaf of an exception's `detail` through `force_str`
    (`_get_error_details`), and the result is an `ErrorDetail` -- which subclasses
    `str`. Two concrete corruptions follow, both live on the wire before this
    class existed:

    * a numeric detail such as ``"rank": 2`` ships as ``"2"``, and
    * a null detail such as ``"unmatched": None`` ships as the **string**
      ``"None"`` -- which is *truthy*, so a frontend testing
      ``if (detail.unmatched)`` renders the literal text "None" and concludes a
      reason was recorded when none was.

    These bodies are data, not validation prose, so the raw dict is restored
    after `super().__init__()`. DRF's handler passes a dict `detail` straight
    through to the response, so nothing downstream re-coerces it.
    """

    def __init__(self, body: dict):
        super().__init__(body)
        self.detail = body


class InvalidParameter(StructuredDetail, APIException):
    """A query parameter was malformed, out of range, or not whitelisted."""

    status_code = 400
    default_detail = "Invalid query parameter."
    default_code = "invalid_parameter"

    def __init__(self, param: str, message: str, *, allowed: Sequence[str] | None = None):
        self.param = param
        self.allowed = list(allowed or ())
        detail: dict = {"error": "invalid_parameter", "param": param, "message": message}
        if self.allowed:
            detail["allowed"] = self.allowed
        super().__init__(detail)


class UnknownValue(StructuredDetail, APIException):
    """A path segment named something that does not exist, in a closed set."""

    status_code = 404
    default_detail = "Unknown value."
    default_code = "unknown_value"

    def __init__(self, param: str, value: str, *, allowed: Iterable[str]):
        self.param = param
        self.allowed = sorted(allowed)
        super().__init__(
            {
                "error": "unknown_value",
                "param": param,
                "message": f"Unknown {param} {value!r}.",
                "allowed": self.allowed,
            }
        )


class ModelIncomplete(StructuredDetail, APIException):
    """404 for a model that is real but excluded by the completeness rule."""

    status_code = 404
    default_detail = "Model is incomplete."
    default_code = "model_incomplete"

    def __init__(self, key: str, reason: str, *, message: str = "", detail: dict | None = None):
        self.reason = reason
        body: dict = {
            "error": "model_incomplete",
            "model_key": key,
            "reason": reason,
            "message": message
            or (
                "This model exists but has no counterpart in the other source, so it "
                "is not served by the joined endpoints. It remains available through "
                "`/categories/{category}/` and `/unmatched/`."
            ),
        }
        if detail:
            body["detail"] = detail
        super().__init__(body)


def leaderboard_exception_handler(exc, context):
    """DRF's handler, with anything still in DRF's shape wrapped in ours."""
    response = drf_exception_handler(exc, context)
    if response is None:
        # Not an APIException -- a genuine 500. Returning None lets Django's own
        # handler deal with it, which is what we want: it must not be swallowed
        # into a tidy 400-shaped body.
        return None

    data = response.data
    if isinstance(data, dict) and "error" in data:
        # Raised by one of the exceptions above; already in the envelope.
        return response

    response.data = {
        "error": _DEFAULT_CODES.get(response.status_code, "error"),
        "detail": data,
    }
    return response
