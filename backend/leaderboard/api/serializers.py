"""Response shaping.

Plain functions returning dicts, rather than nested DRF `Serializer` classes.
The response shapes here are *compositions* -- one row is a slice of one table
plus three slices of another plus a joined record -- and expressing that as
serializer nesting produces more code than the composition it describes. The
contract that matters is the emitted JSON, and it is pinned by the tests.

Three rules hold across every payload:

* **`null`, never `0`.** The AA spec is explicit that a null means "not
  measured". A zero would draw a real data point at the origin of every chart.
  The same rule applies to empty strings, which become `null`.
* **Optional blocks are present and explicitly `null`**, never absent, so the
  frontend can destructure without a guard.
* **Raw upstream payloads are never exposed.** `LLMModel.raw_payload` and
  `LMArenaEntry.source_metadata` exist for troubleshooting schema drift and stop
  at this boundary.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from ..constants import CATEGORIES, INTERSECTED_CATEGORIES, PRIMARY_CATEGORY
from ..models import LMArenaEntry, LLMModel, SyncRun, UnmatchedRecord

# --------------------------------------------------------------------------- #
# Scalars
# --------------------------------------------------------------------------- #


def iso(value: date | datetime | None) -> str | None:
    """ISO-8601, always UTC and always `Z`-suffixed."""
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value.isoformat()


def number(value: Any) -> float | None:
    """Money comes out of the database as `Decimal`; JSON has no such type.

    Emitted as a float because that is what a charting library consumes. The
    exact value stays in the database, which is where the "no drift when
    summing" property actually matters.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def text(value: str | None) -> str | None:
    """Empty upstream strings are absent data, not the empty string."""
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


# --------------------------------------------------------------------------- #
# Blocks
# --------------------------------------------------------------------------- #


def identity(entry: LMArenaEntry) -> dict[str, Any]:
    """The shared `model` identity block.

    Identical in `/overview/` and `/models/{key}/` so the frontend reuses one
    component. `key` is the agent-side normalized key, which is also what
    `/models/{key}/` accepts.
    """
    return {
        "key": entry.model_key,
        "name": entry.model_name,
        "organization": text(entry.organization),
        "license": text(entry.license),
        "in_agent_set": entry.in_agent_set,
    }


def category_block(entry: LMArenaEntry | None) -> dict[str, Any] | None:
    """The shared per-category metric block. `None` when the model was not
    evaluated in that category -- which is real information, not an error."""
    if entry is None:
        return None
    return {
        "category": entry.category,
        "metric_kind": entry.metric_kind,
        "metric_value": entry.metric_value,
        "metric_lower": entry.metric_lower,
        "metric_upper": entry.metric_upper,
        "metric_variance": entry.metric_variance,
        "sample_size": entry.sample_size,
        "session_count": entry.session_count,
        "rank": entry.rank,
        "model_name": entry.model_name,
        "organization": text(entry.organization),
        "license": text(entry.license),
        "leaderboard_publish_date": iso(entry.leaderboard_publish_date),
        #: The upstream spelling this block came from. Differs from the model's
        #: own name when the row matched through the harness fold.
        "source_key": entry.model_key,
        "matched_by_fold": entry.agent_key is not None and entry.agent_key != entry.model_key,
    }


def aa_block(model: LLMModel | None) -> dict[str, Any] | None:
    if model is None:
        return None
    return {
        "id": model.aa_id,
        "slug": model.slug,
        "name": model.name,
        "creator": (
            {"id": model.creator.aa_id, "name": model.creator.name}
            if model.creator is not None
            else None
        ),
        "release_date": iso(model.release_date),
        "intelligence_index_version": model.intelligence_index_version,
        "intelligence_index": model.intelligence_index,
        "coding_index": model.coding_index,
        "agentic_index": model.agentic_index,
        "intelligence_index_total_cost": number(model.intelligence_index_total_cost),
        "cost_per_task": number(model.cost_per_task),
        "pricing": {
            "price_1m_input_tokens": number(model.price_1m_input_tokens),
            "price_1m_output_tokens": number(model.price_1m_output_tokens),
            "price_1m_cache_hit_tokens": number(model.price_1m_cache_hit_tokens),
            "price_1m_cache_write_tokens": number(model.price_1m_cache_write_tokens),
        },
        "performance": {
            "median_output_tokens_per_second": model.median_output_tokens_per_second,
            "median_time_to_first_token_seconds": model.median_time_to_first_token_seconds,
            "median_time_to_first_answer_token_seconds": (
                model.median_time_to_first_answer_token_seconds
            ),
            "median_end_to_end_response_time_seconds": (
                model.median_end_to_end_response_time_seconds
            ),
        },
        "is_retained": model.is_retained,
        "last_synced_at": iso(model.last_synced_at),
    }


def match_block(entry: LMArenaEntry) -> dict[str, Any] | None:
    """How the AA record was tied to this agent model -- always worth showing,
    because one rung of the ladder is an inference and a reader deserves to know
    when they are looking at it."""
    match = getattr(entry, "aa_match", None)
    if match is None:
        return None
    return {
        "method": match.match_method,
        "confidence": match.confidence,
        "is_manual": match.is_manual,
        "matched_key": match.matched_key,
        "last_matched_at": iso(match.last_matched_at),
    }


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #


def _blocks_for(
    entry: LMArenaEntry,
    blocks: Mapping[str, Mapping[str, LMArenaEntry]],
) -> dict[str, Any]:
    """All four category blocks for one agent model, `agent` included."""
    row: dict[str, Any] = {PRIMARY_CATEGORY: category_block(entry)}
    for category in INTERSECTED_CATEGORIES:
        row[category] = category_block(blocks.get(category, {}).get(entry.model_key))
    return row


def overview_row(
    entry: LMArenaEntry,
    blocks: Mapping[str, Mapping[str, LMArenaEntry]],
) -> dict[str, Any]:
    """One visualization-ready model.

    **Only ever produced for a complete entry** -- see
    `selectors.complete_agent_entries`. The `aa` block is therefore non-null in
    practice; it is emitted through `aa_block` anyway so the shape is stable if
    that guarantee is ever relaxed.
    """
    model = getattr(getattr(entry, "aa_match", None), "model", None)
    return {
        "model": identity(entry),
        "categories": _blocks_for(entry, blocks),
        "aa": aa_block(model),
        "match": match_block(entry),
    }


def category_row(entry: LMArenaEntry) -> dict[str, Any]:
    """One row of a single-source category listing. No completeness guarantee
    here by design -- `/categories/{category}/` deliberately exposes the rows
    the joined endpoints exclude."""
    return {
        "model": {
            "key": entry.model_key,
            "name": entry.model_name,
            "organization": text(entry.organization),
            "license": text(entry.license),
            "agent_key": entry.agent_key,
            "in_agent_set": entry.in_agent_set,
        },
        "category": category_block(entry),
        "matched_by_fold": entry.agent_key is not None and entry.agent_key != entry.model_key,
    }


def aa_row(model: LLMModel) -> dict[str, Any]:
    """One AA record, with a back-reference to the agent model it owns, if any.

    The back-reference is what makes this endpoint usable for single-source
    browsing: a row with `matched_model: null` is a model AA measures that
    LMArena's agent set does not cover, which is exactly the population the
    joined endpoints hide.
    """
    match = getattr(model, "lmarena_match", None)
    return {
        "aa": aa_block(model),
        "matched_model": (
            {
                "key": match.lmarena_entry.model_key,
                "name": match.lmarena_entry.model_name,
                "organization": text(match.lmarena_entry.organization),
                "match_method": match.match_method,
                "confidence": match.confidence,
                "agent": category_block(match.lmarena_entry),
            }
            if match is not None
            else None
        ),
    }


def model_detail(
    entry: LMArenaEntry,
    model: LLMModel | None,
    blocks: Mapping[str, Mapping[str, LMArenaEntry]],
) -> dict[str, Any]:
    """`/models/{key}/` -- every block, explicitly null where absent.

    `provenance` exists so the inferred part of the join is auditable from the
    API itself and not only from the database: a reviewer can see which upstream
    spelling each block came from and whether the harness fold was involved.
    """
    provenance_categories: dict[str, Any] = {}
    for category in INTERSECTED_CATEGORIES:
        block = blocks.get(category, {}).get(entry.model_key)
        if block is None:
            continue
        provenance_categories[category] = {
            "source_key": block.model_key,
            "source_name": block.model_name,
            "matched_by_fold": block.agent_key is not None and block.agent_key != block.model_key,
            "last_synced_at": iso(block.last_synced_at),
        }

    match = getattr(entry, "aa_match", None)
    return {
        "model": identity(entry),
        "categories": _blocks_for(entry, blocks),
        "aa": aa_block(model),
        "match": match_block(entry),
        "provenance": {
            "agent_key": entry.model_key,
            "aa_match_method": match.match_method if match is not None else None,
            "aa_match_is_manual": bool(match is not None and match.is_manual),
            "category_sources": provenance_categories,
            "lmarena_last_synced_at": iso(entry.last_synced_at),
        },
    }


def unmatched_row(record: UnmatchedRecord) -> dict[str, Any]:
    return {
        "source": record.source,
        "category": record.category or None,
        "reason": record.reason,
        "model_key": record.model_key,
        "model_name": text(record.model_name),
        "organization": text(record.organization),
        "occurrences": record.occurrences,
        "is_current": record.is_current,
        "first_seen_at": iso(record.first_seen_at),
        "last_seen_at": iso(record.last_seen_at),
        "detail": record.detail or {},
    }


def sync_run_row(run: SyncRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "source": run.source,
        "status": run.status,
        "triggered_by": text(run.triggered_by),
        "dry_run": run.dry_run,
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
        "duration_ms": run.duration_ms,
        "records_seen": run.records_seen,
        "records_created": run.records_created,
        "records_updated": run.records_updated,
        "records_unchanged": run.records_unchanged,
        "records_deactivated": run.records_deactivated,
        "records_failed": run.records_failed,
        "records_deduplicated": run.records_deduplicated,
        "anomalies_recorded": run.anomalies_recorded,
        "error_code": text(run.error_code),
        "error_message": text(run.error_message),
    }


ALL_CATEGORIES: tuple[str, ...] = CATEGORIES

__all__ = [
    "ALL_CATEGORIES",
    "aa_block",
    "aa_row",
    "category_block",
    "category_row",
    "identity",
    "iso",
    "match_block",
    "model_detail",
    "number",
    "overview_row",
    "sync_run_row",
    "text",
    "unmatched_row",
]
