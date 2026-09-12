"""Turn raw upstream payloads into validated, typed values.

This is the only place that knows the shape of an upstream record. Everything
downstream works with the `Parsed*` dataclasses, so a source schema change
breaks in exactly one module and produces a `validation_failed` anomaly rather
than a half-written row.

Coercion rules, applied uniformly:

* A missing or empty value becomes ``None``. It is **never** coerced to ``0`` --
  the AA spec is explicit that a null means "not measured", and zero is a real
  data point that would land at the origin of every scatter plot.
* An explicit ``0.0`` survives as ``0.0``.
* A value that is present but unparseable is a `ValidationError`, not a silent
  drop: it means the schema moved under us.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .constants import CATEGORY_METRIC_KIND, Category, MetricKind
from .normalization import normalize_model_key

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class ValidationError(ValueError):
    """A payload did not match the schema we expect from the source."""

    def __init__(self, message: str, *, field: str | None = None):
        super().__init__(message)
        self.field = field


# --------------------------------------------------------------------------- #
# Coercers
# --------------------------------------------------------------------------- #


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def as_float(value: Any, *, field: str = "") -> float | None:
    if _is_blank(value):
        return None
    if isinstance(value, bool):
        raise ValidationError(f"{field or 'value'} expected a number, got a boolean", field=field)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field or 'value'} is not a number: {value!r}", field=field) from exc


def as_decimal(value: Any, *, field: str = "") -> Decimal | None:
    """Money and prices. Decimal rather than float so costs sum without drift."""
    if _is_blank(value):
        return None
    if isinstance(value, bool):
        raise ValidationError(f"{field or 'value'} expected a number, got a boolean", field=field)
    try:
        # str() first: Decimal(0.1) would capture the binary float's noise.
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field or 'value'} is not a decimal: {value!r}", field=field) from exc


def as_int(value: Any, *, field: str = "") -> int | None:
    if _is_blank(value):
        return None
    if isinstance(value, bool):
        raise ValidationError(f"{field or 'value'} expected an integer, got a boolean", field=field)
    if isinstance(value, int):
        return value
    try:
        # Some LMArena configs publish counts as float64.
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field or 'value'} is not an integer: {value!r}", field=field) from exc


def as_text(value: Any) -> str:
    if _is_blank(value):
        return ""
    return str(value)


def as_date(value: Any, *, field: str = "") -> date | None:
    """Parse an ISO date or datetime. The sources publish both."""
    if _is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise ValidationError(f"{field or 'value'} is not a date: {value!r}", field=field) from exc


def dig(payload: Mapping[str, Any], *path: str) -> Any:
    """Read a nested key without raising on a missing or null intermediate."""
    node: Any = payload
    for step in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(step)
    return node


def require_mapping(payload: Any, *, what: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValidationError(f"{what} must be an object, got {type(payload).__name__}")
    return payload


# --------------------------------------------------------------------------- #
# LMArena
# --------------------------------------------------------------------------- #

#: Columns every LMArena split must carry, regardless of category.
LMARENA_COMMON_COLUMNS: frozenset[str] = frozenset(
    {
        "model_name",
        "organization",
        "license",
        "rank",
        "category",
        "leaderboard_publish_date",
    }
)

#: Category-specific column families. `agent` publishes an Elo-style `score` with
#: an observation/session count; the other three publish a Bradley-Terry
#: `rating` with a variance and a vote count. Both are normalized onto the same
#: `metric_*` / `sample_size` / `session_count` shape.
LMARENA_FIELD_MAP: dict[str, dict[str, str | None]] = {
    Category.AGENT.value: {
        "metric_value": "score",
        "metric_lower": "score_ci_lower",
        "metric_upper": "score_ci_upper",
        "metric_variance": None,
        "sample_size": "observation_count",
        "session_count": "session_count",
    },
    Category.DOCUMENT.value: {
        "metric_value": "rating",
        "metric_lower": "rating_lower",
        "metric_upper": "rating_upper",
        "metric_variance": "variance",
        "sample_size": "vote_count",
        "session_count": None,
    },
}
LMARENA_FIELD_MAP[Category.SEARCH.value] = LMARENA_FIELD_MAP[Category.DOCUMENT.value]
LMARENA_FIELD_MAP[Category.WEBDEV.value] = LMARENA_FIELD_MAP[Category.DOCUMENT.value]


def required_columns(category: str) -> frozenset[str]:
    """The columns a split must expose for us to ingest it at all."""
    if category not in LMARENA_FIELD_MAP:
        raise ValidationError(f"unknown LMArena category: {category!r}")
    mapping = LMARENA_FIELD_MAP[category]
    specific = {column for column in mapping.values() if column}
    return LMARENA_COMMON_COLUMNS | specific


def check_columns(category: str, columns) -> None:
    """Fail the *category* (not the run) when the upstream schema drifts."""
    present = set(columns)
    missing = sorted(required_columns(category) - present)
    if missing:
        raise ValidationError(
            f"LMArena split {category!r} is missing required columns: {', '.join(missing)}",
            field="columns",
        )


@dataclass(frozen=True)
class ParsedLMArenaRow:
    category: str
    model_name: str
    model_key: str
    organization: str
    license: str
    rank: int | None
    metric_kind: str
    metric_value: float | None
    metric_lower: float | None
    metric_upper: float | None
    metric_variance: float | None
    sample_size: int | None
    session_count: int | None
    leaderboard_publish_date: date | None
    source_metadata: dict[str, Any]


def parse_lmarena_row(raw: Mapping[str, Any], category: str) -> ParsedLMArenaRow:
    if category not in LMARENA_FIELD_MAP:
        raise ValidationError(f"unknown LMArena category: {category!r}", field="category")

    model_name = as_text(raw.get("model_name"))
    if not model_name:
        raise ValidationError("model_name is empty", field="model_name")

    mapping = LMARENA_FIELD_MAP[category]

    def read(slot: str) -> Any:
        column = mapping[slot]
        return None if column is None else raw.get(column)

    return ParsedLMArenaRow(
        category=category,
        model_name=model_name,
        model_key=normalize_model_key(model_name),
        organization=as_text(raw.get("organization")),
        license=as_text(raw.get("license")),
        rank=as_int(raw.get("rank"), field="rank"),
        metric_kind=CATEGORY_METRIC_KIND[category],
        metric_value=as_float(read("metric_value"), field="metric_value"),
        metric_lower=as_float(read("metric_lower"), field="metric_lower"),
        metric_upper=as_float(read("metric_upper"), field="metric_upper"),
        metric_variance=as_float(read("metric_variance"), field="metric_variance"),
        sample_size=as_int(read("sample_size"), field="sample_size"),
        session_count=as_int(read("session_count"), field="session_count"),
        leaderboard_publish_date=as_date(
            raw.get("leaderboard_publish_date"), field="leaderboard_publish_date"
        ),
        source_metadata={
            "upstream_category": as_text(raw.get("category")),
        },
    )


# --------------------------------------------------------------------------- #
# Artificial Analysis
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ParsedAAModel:
    aa_id: str
    slug: str
    name: str
    creator_aa_id: str | None
    creator_name: str | None
    release_date: date | None
    intelligence_index_version: float | None
    intelligence_index: float | None
    coding_index: float | None
    agentic_index: float | None
    intelligence_index_total_cost: Decimal | None
    cost_per_task: Decimal | None
    price_1m_input_tokens: Decimal | None
    price_1m_output_tokens: Decimal | None
    price_1m_cache_hit_tokens: Decimal | None
    price_1m_cache_write_tokens: Decimal | None
    median_output_tokens_per_second: float | None
    median_time_to_first_token_seconds: float | None
    median_time_to_first_answer_token_seconds: float | None
    median_end_to_end_response_time_seconds: float | None
    raw_payload: dict[str, Any]


def parse_aa_model(
    raw: Mapping[str, Any],
    *,
    intelligence_index_version: Any = None,
) -> ParsedAAModel:
    """Parse one entry of an AA `/language/models/free` `data` array.

    `intelligence_index_version` is a *response*-level field, not a per-record
    one, so it is passed in rather than read from `raw`.
    """
    payload = require_mapping(raw, what="AA model record")

    aa_id = as_text(payload.get("id"))
    name = as_text(payload.get("name"))
    slug = as_text(payload.get("slug"))
    if not aa_id:
        raise ValidationError("AA model record has no id", field="id")
    if not slug:
        raise ValidationError("AA model record has no slug", field="slug")
    if not name:
        raise ValidationError("AA model record has no name", field="name")

    creator = payload.get("model_creator")
    creator_aa_id = creator_name = None
    if isinstance(creator, Mapping):
        creator_aa_id = as_text(creator.get("id")) or None
        creator_name = as_text(creator.get("name")) or None

    return ParsedAAModel(
        aa_id=aa_id,
        slug=slug,
        name=name,
        creator_aa_id=creator_aa_id,
        creator_name=creator_name,
        release_date=as_date(payload.get("release_date"), field="release_date"),
        intelligence_index_version=as_float(
            intelligence_index_version, field="intelligence_index_version"
        ),
        intelligence_index=as_float(
            dig(payload, "evaluations", "artificial_analysis_intelligence_index"),
            field="intelligence_index",
        ),
        coding_index=as_float(
            dig(payload, "evaluations", "artificial_analysis_coding_index"),
            field="coding_index",
        ),
        agentic_index=as_float(
            dig(payload, "evaluations", "artificial_analysis_agentic_index"),
            field="agentic_index",
        ),
        intelligence_index_total_cost=as_decimal(
            dig(payload, "artificial_analysis_intelligence_index_cost", "total_cost"),
            field="intelligence_index_total_cost",
        ),
        cost_per_task=as_decimal(
            dig(
                payload,
                "artificial_analysis_intelligence_index_cost",
                "cost_per_task",
                "total_cost",
            ),
            field="cost_per_task",
        ),
        price_1m_input_tokens=as_decimal(
            dig(payload, "pricing", "price_1m_input_tokens"), field="price_1m_input_tokens"
        ),
        price_1m_output_tokens=as_decimal(
            dig(payload, "pricing", "price_1m_output_tokens"), field="price_1m_output_tokens"
        ),
        price_1m_cache_hit_tokens=as_decimal(
            dig(payload, "pricing", "price_1m_cache_hit_tokens"),
            field="price_1m_cache_hit_tokens",
        ),
        price_1m_cache_write_tokens=as_decimal(
            dig(payload, "pricing", "price_1m_cache_write_tokens"),
            field="price_1m_cache_write_tokens",
        ),
        median_output_tokens_per_second=as_float(
            dig(payload, "performance", "median_output_tokens_per_second"),
            field="median_output_tokens_per_second",
        ),
        median_time_to_first_token_seconds=as_float(
            dig(payload, "performance", "median_time_to_first_token_seconds"),
            field="median_time_to_first_token_seconds",
        ),
        median_time_to_first_answer_token_seconds=as_float(
            dig(payload, "performance", "median_time_to_first_answer_token_seconds"),
            field="median_time_to_first_answer_token_seconds",
        ),
        median_end_to_end_response_time_seconds=as_float(
            dig(payload, "performance", "median_end_to_end_response_time_seconds"),
            field="median_end_to_end_response_time_seconds",
        ),
        raw_payload=dict(payload),
    )


__all__ = [
    "ValidationError",
    "ParsedLMArenaRow",
    "ParsedAAModel",
    "LMARENA_COMMON_COLUMNS",
    "LMARENA_FIELD_MAP",
    "MetricKind",
    "as_date",
    "as_decimal",
    "as_float",
    "as_int",
    "as_text",
    "check_columns",
    "dig",
    "parse_aa_model",
    "parse_lmarena_row",
    "require_mapping",
    "required_columns",
]
