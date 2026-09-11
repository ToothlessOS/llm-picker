"""Schema coercion at the source boundary.

The single most consequential rule here is **upstream `null` means "not
measured", and must never become `0`**. The AA OpenAPI spec is explicit about it,
and a zero is not a neutral stand-in: it draws a real data point at the origin of
every cost and latency chart, which reads as "this model is free" or "this model
responds instantly".
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from leaderboard.constants import MetricKind
from leaderboard.validation import (
    LMARENA_COMMON_COLUMNS,
    ValidationError,
    check_columns,
    parse_aa_model,
    parse_lmarena_row,
    required_columns,
)


# --------------------------------------------------------------------------- #
# Artificial Analysis
# --------------------------------------------------------------------------- #


def aa_payload(**overrides):
    payload = {"id": "uuid-1", "slug": "gpt-5-5", "name": "GPT-5.5 (xhigh)"}
    payload.update(overrides)
    return payload


class TestParseAaModel:
    @pytest.mark.parametrize("field", ["id", "slug", "name"])
    def test_identity_fields_are_required(self, field):
        payload = aa_payload()
        payload[field] = ""

        with pytest.raises(ValidationError) as excinfo:
            parse_aa_model(payload)

        assert excinfo.value.field == field

    def test_missing_metric_is_none_not_zero(self):
        model = parse_aa_model(aa_payload())

        assert model.cost_per_task is None
        assert model.intelligence_index is None
        assert model.median_time_to_first_token_seconds is None

    def test_explicit_zero_is_preserved(self):
        """A real measured zero is data; it must survive as 0, not become null.

        The inverse of the null rule, and just as important: a genuinely free
        model has a cost of 0, and dropping it would erase a real comparison.
        """
        model = parse_aa_model(
            aa_payload(
                artificial_analysis_intelligence_index_cost={
                    "cost_per_task": {"total_cost": 0.0}
                },
                evaluations={"artificial_analysis_intelligence_index": 0},
                pricing={"price_1m_input_tokens": 0},
            )
        )

        assert model.cost_per_task == Decimal("0.0")
        assert model.intelligence_index == 0.0
        assert model.price_1m_input_tokens == Decimal("0")

    def test_money_is_decimal_and_measurements_are_float(self):
        """Money in `Decimal` (no drift when summed); indices in `float`.

        The two are typed differently on purpose, straight from the source
        contract: a cost is currency, an index is an approximate measurement.
        """
        model = parse_aa_model(
            aa_payload(
                artificial_analysis_intelligence_index_cost={
                    "total_cost": "0.123456",
                    "cost_per_task": {"total_cost": "0.000123"},
                },
                pricing={"price_1m_output_tokens": "15.00"},
                evaluations={"artificial_analysis_intelligence_index": 42.5},
                performance={"median_output_tokens_per_second": 99.1},
            )
        )

        assert isinstance(model.cost_per_task, Decimal)
        assert isinstance(model.price_1m_output_tokens, Decimal)
        assert isinstance(model.intelligence_index, float)
        assert isinstance(model.median_output_tokens_per_second, float)

    def test_the_two_cost_fields_read_different_depths(self):
        """A real schema trap, taken from the live payload.

        AA's cost object is::

            {"total_cost": 59.99, "cost_per_task": {"total_cost": 0.0502}}

        The chart total is a scalar; the per-task figure is an *object* one
        level deeper. So `cost_per_task` must be read at depth 3 and
        `intelligence_index_total_cost` at depth 2. Reading either at the wrong
        depth yields `None` silently -- the value simply never appears, with no
        error to explain it. Verified against 134 populated rows on the live API.
        """
        model = parse_aa_model(
            aa_payload(
                artificial_analysis_intelligence_index_cost={
                    "total_cost": 59.99,
                    "cost_per_task": {"total_cost": 0.0502},
                }
            )
        )

        assert model.intelligence_index_total_cost == Decimal("59.99")
        assert model.cost_per_task == Decimal("0.0502")

    def test_a_scalar_cost_per_task_is_not_silently_accepted(self):
        """The wrong shape must not be coerced into a right-looking number."""
        model = parse_aa_model(
            aa_payload(artificial_analysis_intelligence_index_cost={"cost_per_task": 0.0502})
        )

        assert model.cost_per_task is None

    def test_absent_and_unparseable_are_not_the_same_thing(self):
        """The two ways a field can be missing are treated oppositely, on purpose.

        * **Absent or `null`** means the source did not measure it. That is real
          information, and it becomes `None` -> a `NULL` column -> "not measured"
          in the API.
        * **Present but unparseable** means we do not understand what arrived. It
          raises, and the caller rejects the whole record.

        Rejecting the record rather than nulling the one field is the
        conservative choice: a payload whose shape has drifted is not a payload
        to half-trust, and a partially-ingested record is indistinguishable
        downstream from a complete one. `refresh` catches this per row, records a
        `validation_failed` anomaly, and skips it -- so one bad record costs one
        record, not the run. If *every* record fails, the run aborts rather than
        writing an empty catalogue.
        """
        absent = parse_aa_model(aa_payload())
        assert absent.cost_per_task is None

        with pytest.raises(ValidationError) as excinfo:
            parse_aa_model(
                aa_payload(
                    artificial_analysis_intelligence_index_cost={
                        "cost_per_task": {"total_cost": "not-a-number"}
                    }
                )
            )

        assert excinfo.value.field == "cost_per_task"

    def test_a_boolean_is_never_a_number(self):
        """`True` is an `int` in Python; it must not silently become cost `1`.

        JSON `true` reaching a numeric field means the schema moved, and a cost
        of exactly 1.0 looks like a plausible measurement once stored.
        """
        with pytest.raises(ValidationError):
            parse_aa_model(
                aa_payload(
                    artificial_analysis_intelligence_index_cost={
                        "cost_per_task": {"total_cost": True}
                    }
                )
            )

    def test_creator_is_extracted_from_the_nested_object(self):
        model = parse_aa_model(
            aa_payload(model_creator={"id": "creator-1", "name": "Anthropic"})
        )

        assert model.creator_aa_id == "creator-1"
        assert model.creator_name == "Anthropic"

    def test_absent_creator_is_none(self):
        model = parse_aa_model(aa_payload())

        assert model.creator_aa_id is None
        assert model.creator_name is None

    def test_release_date_is_parsed_to_a_date(self):
        model = parse_aa_model(aa_payload(release_date="2026-05-04"))

        assert model.release_date == date(2026, 5, 4)

    def test_raw_payload_is_retained_for_troubleshooting(self):
        payload = aa_payload(extra_field="kept")

        assert parse_aa_model(payload).raw_payload["extra_field"] == "kept"


# --------------------------------------------------------------------------- #
# LMArena
# --------------------------------------------------------------------------- #


class TestRequiredColumns:
    def test_agent_needs_its_confidence_bounds(self):
        assert {"score", "score_ci_lower", "score_ci_upper"} <= required_columns("agent")

    def test_rating_categories_need_variance_and_votes(self):
        for category in ("document", "search", "webdev"):
            columns = required_columns(category)
            assert {"rating", "rating_lower", "rating_upper", "variance", "vote_count"} <= columns
            # The agent-only columns are not demanded of them.
            assert "score" not in columns

    def test_every_category_needs_the_common_columns(self):
        for category in ("agent", "document", "search", "webdev"):
            assert LMARENA_COMMON_COLUMNS <= required_columns(category)

    def test_unknown_category_is_rejected(self):
        with pytest.raises(ValidationError):
            required_columns("nope")

    def test_missing_column_names_itself(self):
        with pytest.raises(ValidationError) as excinfo:
            check_columns("agent", ["model_name", "organization"])

        assert excinfo.value.field == "columns"
        assert "score" in str(excinfo.value)

    def test_complete_columns_pass(self):
        check_columns("document", required_columns("document"))


class TestParseLMArenaRow:
    def test_agent_row_carries_score_semantics(self):
        row = parse_lmarena_row(
            {
                "model_name": "Claude Opus 5 (High)",
                "organization": "anthropic",
                "license": "Proprietary",
                "rank": 3,
                "category": "overall",
                "leaderboard_publish_date": "2026-09-08",
                "score": 0.114,
                "score_ci_lower": 0.096,
                "score_ci_upper": 0.131,
                "observation_count": 2_794_373,
                "session_count": 23_232,
            },
            "agent",
        )

        assert row.metric_kind == MetricKind.SCORE.value
        assert row.model_key == "claude-opus-5-high"
        assert row.sample_size == 2_794_373
        assert row.session_count == 23_232
        assert row.metric_variance is None  # agent publishes no variance

    def test_rating_row_carries_rating_semantics(self):
        row = parse_lmarena_row(
            {
                "model_name": "claude-opus-5-high",
                "organization": "anthropic",
                "license": "Proprietary",
                "rank": 1,
                "category": "overall",
                "leaderboard_publish_date": "2026-07-30",
                "rating": 1520.1,
                "rating_lower": 1505.4,
                "rating_upper": 1534.7,
                "variance": 55.6,
                "vote_count": 1663,
            },
            "document",
        )

        assert row.metric_kind == MetricKind.RATING.value
        assert row.metric_variance == 55.6
        assert row.session_count is None  # rating categories publish no sessions

    def test_missing_metric_stays_none(self):
        row = parse_lmarena_row(
            {
                "model_name": "Sparse Model",
                "organization": "",
                "license": "",
                "rank": 1,
                "category": "overall",
                "leaderboard_publish_date": "2026-09-08",
                "score": None,
                "score_ci_lower": None,
                "score_ci_upper": None,
                "observation_count": None,
                "session_count": None,
            },
            "agent",
        )

        assert row.metric_value is None
        assert row.sample_size is None

    def test_source_metadata_records_the_upstream_split_label(self):
        """DOCUMENTED LIMITATION, not desired behaviour.

        `source_metadata` keeps the upstream `category` column -- always
        `"overall"`, and the one upstream field with no first-class home -- but
        **does not retain unrecognised extra columns or their values**. So if
        LMArena ever renamed `score`, `check_columns` would fail the category
        loudly, but the stored rows would hold no record of what arrived.

        This is asymmetric with Artificial Analysis, which keeps the whole
        record in `raw_payload`. The reason is that AA's payloads are uniform and
        JSON-safe, while LMArena rows are wide and carry types we do not control;
        storing them verbatim risks a serialization failure inside the write
        transaction. Recorded here so the gap is visible rather than assumed.
        """
        row = parse_lmarena_row(
            {
                "model_name": "M",
                "organization": "o",
                "license": "l",
                "rank": 1,
                "category": "overall",
                "leaderboard_publish_date": "2026-09-08",
                "score": 1.0,
                "score_ci_lower": 0.9,
                "score_ci_upper": 1.1,
                "observation_count": 1,
                "session_count": 1,
                "some_new_column": "not retained",
            },
            "agent",
        )

        assert row.source_metadata == {"upstream_category": "overall"}

    def test_blank_name_is_a_validation_error(self):
        with pytest.raises(ValidationError):
            parse_lmarena_row(
                {
                    "model_name": "  ",
                    "organization": "o",
                    "license": "l",
                    "rank": 1,
                    "category": "overall",
                    "leaderboard_publish_date": "2026-09-08",
                    "score": 1.0,
                    "score_ci_lower": 0.9,
                    "score_ci_upper": 1.1,
                    "observation_count": 1,
                    "session_count": 1,
                },
                "agent",
            )
