"""Query-parameter parsing.

Everything the API accepts is parsed here, once, so that every endpoint rejects
a bad value the same way and names the offending parameter in the same field.

Two deliberate choices:

* **Whitelists, not reflection.** Ordering and metric filters are resolved
  through explicit maps in `constants.py`. A typo in `?ordering=` is a 400 that
  lists the valid keys, rather than a silently ignored parameter or an ORM error
  leaked to the client.
* **Clamp what is safe, reject what is not.** `page_size` above the cap is
  clamped; a non-integer is a 400. Ordering is always rejected when unknown,
  because silently falling back to the default would make the response look
  correct while ignoring what the caller asked for.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from django.db.models import F

from .errors import InvalidParameter

_TRUE = {"1", "true", "t", "yes", "y", "on"}
_FALSE = {"0", "false", "f", "no", "n", "off"}


def get_bool(request, name: str, *, default: bool | None = None) -> bool | None:
    raw = request.query_params.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise InvalidParameter(
        name,
        f"{name} must be a boolean, got {raw!r}.",
        allowed=["true", "false"],
    )


def get_int(
    request,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    raw = request.query_params.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        raise InvalidParameter(name, f"{name} must be an integer, got {raw!r}.") from None
    if minimum is not None and value < minimum:
        raise InvalidParameter(name, f"{name} must be at least {minimum}, got {value}.")
    if maximum is not None and value > maximum:
        raise InvalidParameter(name, f"{name} must be at most {maximum}, got {value}.")
    return value


def get_float(request, name: str) -> float | None:
    raw = request.query_params.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        raise InvalidParameter(name, f"{name} must be a number, got {raw!r}.") from None


def get_text(request, name: str) -> str | None:
    raw = request.query_params.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def get_choice(
    request,
    name: str,
    allowed: Sequence[str],
    *,
    default: str | None = None,
) -> str | None:
    value = get_text(request, name)
    if value is None:
        return default
    if value not in allowed:
        raise InvalidParameter(
            name, f"Unknown {name} {value!r}.", allowed=sorted(allowed)
        )
    return value


def get_list(
    request,
    name: str,
    allowed: Sequence[str],
) -> list[str] | None:
    """A comma-separated subset of `allowed`. `None` means "not supplied"."""
    value = get_text(request, name)
    if value is None:
        return None
    if value in {"all", "*"}:
        return list(allowed)
    if value == "none":
        return []
    items = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [item for item in items if item not in allowed]
    if unknown:
        raise InvalidParameter(
            name,
            f"Unknown {name} value(s): {', '.join(sorted(unknown))}.",
            allowed=sorted(allowed),
        )
    return items


def get_ordering(
    request,
    *,
    allowed: Mapping[str, str],
    default: Sequence[str],
) -> list[Any]:
    """Resolve `?ordering=` into ORM expressions.

    Every term is emitted `nulls_last`, because SQLite's default is NULL-first
    and the two sources publish NULL for "not measured". Without this, every
    unmeasured model would sort to the top of a chart built from the default
    ordering -- the exact opposite of what a reader wants.

    A final `pk` tiebreak is appended unconditionally. Without it, rows that tie
    on the requested field have no defined order and can move *between pages* of
    the same result set, which shows up as duplicated and missing rows in the
    frontend's table.
    """
    raw = request.query_params.get("ordering")
    terms = list(default) if raw is None or raw.strip() == "" else [
        term.strip() for term in raw.split(",") if term.strip()
    ]
    if not terms:
        raise InvalidParameter(
            "ordering",
            "ordering must name at least one field.",
            allowed=sorted(allowed),
        )

    expressions: list[Any] = []
    for term in terms:
        descending = term.startswith("-")
        key = term[1:] if descending else term
        lookup = allowed.get(key)
        if lookup is None:
            raise InvalidParameter(
                "ordering",
                f"Unknown ordering field {key!r}.",
                allowed=sorted(allowed),
            )
        expression = F(lookup)
        expressions.append(
            expression.desc(nulls_last=True) if descending else expression.asc(nulls_last=True)
        )

    expressions.append(F("pk").asc())
    return expressions
