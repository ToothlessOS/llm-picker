"""Normalization is the foundation everything else stands on.

If `normalize_model_key` is wrong, every match is wrong, and the failure is
silent -- two spellings of the *same* model simply stop joining, or two
*different* models start. So the cases here are the real upstream pairs, taken
from live data rather than invented.
"""

from __future__ import annotations

import pytest

from leaderboard.constants import MatchMethod
from leaderboard.matching import match_aa_model
from leaderboard.normalization import (
    effort_from_name,
    harness_fold,
    has_effort_marker,
    normalize_model_key,
)
from leaderboard.tests.factories import agent_index


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # LMArena `agent` display names -> slug space. This conversion is the
        # whole reason cross-category joining is possible at all.
        ("Claude Opus 5 (High)", "claude-opus-5-high"),
        ("GPT 5.5 (xHigh)", "gpt-5-5-xhigh"),
        ("GPT 5.6 Sol (xHigh)", "gpt-5-6-sol-xhigh"),
        ("Muse Spark 1.2 (xHigh)", "muse-spark-1-2-xhigh"),
        ("DeepSeek V4 Pro (High) (0813)", "deepseek-v4-pro-high-0813"),
        # LMArena non-agent slugs -> the same space, unchanged.
        ("claude-opus-5-high", "claude-opus-5-high"),
        ("gpt-5.6-sol-xhigh", "gpt-5-6-sol-xhigh"),
        ("claude-haiku-4-5-20251001", "claude-haiku-4-5-20251001"),
        # Artificial Analysis names.
        ("GPT-5.5 (xhigh)", "gpt-5-5-xhigh"),
        ("MiMo-V2.5-Pro", "mimo-v2-5-pro"),
        ("Qwen3.8-Flash-Next", "qwen3-8-flash-next"),
        ("Claude 3.5 Sonnet (June '24)", "claude-3-5-sonnet-june-24"),
        # Punctuation, case and spacing collapse; unicode does not survive.
        ("  Weird   Name!!  ", "weird-name"),
        ("Grok 4.6 (high)", "grok-4-6-high"),
        ("Modèle Accentué", "modele-accentue"),
        # Empty and absent input are the same thing: no identity.
        ("", ""),
        ("   ", ""),
        (None, ""),
    ],
)
def test_normalize_model_key(raw, expected):
    assert normalize_model_key(raw) == expected


def test_normalization_is_idempotent():
    """Normalizing an already-normalized key must not move it.

    This is not decorative: `agent_key` is compared against `model_key` in the
    read path, and a second pass that changed the value would make a folded row
    silently un-findable.
    """
    for raw in ("Claude Opus 5 (High)", "gpt-5.6-sol-xhigh", "GPT 5.5 (xHigh)", "Qwen3.8 Max"):
        once = normalize_model_key(raw)
        assert normalize_model_key(once) == once


def test_variant_suffix_is_preserved_not_folded():
    """Reasoning effort is part of a model's identity, not decoration.

    Folding it away was tried against real data and produced exactly one match,
    and that match was wrong (`gpt-5.5-high` -> `"GPT 5.5"` when
    `"GPT 5.5 (xHigh)"` is the true sibling). The keys must stay distinct.
    """
    base = normalize_model_key("GPT 5.5")
    high = normalize_model_key("GPT 5.5 (High)")
    xhigh = normalize_model_key("GPT 5.5 (xHigh)")
    assert len({base, high, xhigh}) == 3


class TestHasEffortMarker:
    @pytest.mark.parametrize(
        "key",
        ["gpt-5-5-xhigh", "claude-opus-5-high", "gpt-5-5-low", "qwen3-8-27b-non-reasoning"],
    )
    def test_detects_markers(self, key):
        assert has_effort_marker(key) is True

    @pytest.mark.parametrize("key", ["gpt-5-5", "mimo-v2-5-pro", "claude-opus-5-high-32k", ""])
    def test_silent_keys(self, key):
        assert has_effort_marker(key) is False

    def test_max_is_treated_as_effort_even_where_it_is_part_of_a_name(self):
        """`max` is ambiguous upstream and the check resolves it the safe way.

        It is a genuine Anthropic effort level (`Claude Opus 5 (Max)`) and also
        part of Qwen's model name (`Qwen3.8 Max`). Treating it as effort means
        the slug rung is skipped for Qwen too -- which costs nothing, because
        those records resolve on the *name* rung before the slug is ever
        consulted. The failure mode of the opposite choice would be worse: a
        slug carrying Max numbers onto a base entry.
        """
        assert has_effort_marker(normalize_model_key("Qwen3.8 Max")) is True
        # And the name rung still resolves it correctly, so nothing is lost.
        index = agent_index("Qwen3.8 Max")
        outcome = match_aa_model(index, name="Qwen3.8 Max", slug="qwen3-8-max")
        assert outcome.method == MatchMethod.EXACT_NAME.value

    def test_verbose_aa_phrasing_is_still_invisible_to_the_marker_check(self):
        """The marker's silence on AA's prose dialect is deliberate and permanent.

        Artificial Analysis spells Claude and DeepSeek effort levels out in prose
        -- `"Claude Opus 5 (Adaptive Reasoning, High Effort)"` -- instead of the
        terse `"(high)"` its OpenAI-family rows use. The trailing-token check
        cannot see that, so the slug rung is *not* skipped for those records.

        That is the correct behaviour for *this* function, whose only job is to
        gate the bare-slug rung. It is not a limitation any more: the prose is
        read by `effort_from_name`, which answers a different question and feeds
        the stated-effort rung. See `TestEffortFromName` below for that reader and
        `test_matching.TestAaStatedEffortSlugRung` for the rung it drives.

        Widening this function to cover the verbose form would silently reopen the
        bare-slug rung for exactly the records this design closes it on, so the
        two must not be merged.
        """
        assert has_effort_marker(normalize_model_key("Claude Opus 5 (Adaptive Reasoning, High Effort)")) is False
        assert has_effort_marker(normalize_model_key("DeepSeek V4 Pro 0813 (Reasoning, Max Effort)")) is False

        # The divergence, stated: same input, two different questions. The prose
        # record is invisible to the gate yet perfectly legible to the reader.
        assert effort_from_name("Claude Opus 5 (Adaptive Reasoning, High Effort)") == "high"


class TestEffortFromName:
    """What AA's `name` *states*, as opposed to what `has_effort_marker` sees.

    These are two different questions and the tests are kept apart so neither
    function can be "simplified" into the other.
    """

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            # The verbose prose dialect. The last one is load-bearing: the effort
            # is not adjacent to the end of the name, because AA appends a
            # fallback clause after it.
            ("Claude Opus 5 (Adaptive Reasoning, Max Effort)", "max"),
            ("Claude Opus 5 (Adaptive Reasoning, High Effort)", "high"),
            ("Claude Opus 5 (Adaptive Reasoning, Xhigh Effort)", "xhigh"),
            ("Claude Opus 5 (Adaptive Reasoning, Medium Effort)", "medium"),
            ("Claude Fable 5.1 (Adaptive Reasoning, Low Effort, Default Fallback)", "low"),
            ("DeepSeek V4.1 Flash (Reasoning, Max Effort)", "max"),
            (
                "Claude Fable 5.1 (Adaptive Reasoning, Max Effort, Default Fallback)",
                "max",
            ),
        ],
    )
    def test_verbose_prose_levels_are_read(self, name, expected):
        assert effort_from_name(name) == expected

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("GPT-5.5 (xhigh)", "xhigh"),
            ("GLM-5.2 (max)", "max"),
            ("Gemini 3.6 Flash (high)", "high"),
            ("GPT-5.4 (low)", "low"),
            # The two-token level, mirroring `has_effort_marker`.
            ("Nova 2.0 Lite (Non-reasoning)", "non-reasoning"),
        ],
    )
    def test_terse_parentheticals_are_read(self, name, expected):
        assert effort_from_name(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "MiMo-V2.5-Pro",
            "A.X-K2",
            "Hy3",
            # Says "Reasoning" but names no level -- so nothing is stated, and
            # the rung must stay silent rather than assume.
            "DeepSeek V3.2 (Reasoning)",
            "Claude 4 Opus (Reasoning)",
            "",
            None,
        ],
    )
    def test_names_stating_no_level_return_none(self, name):
        assert effort_from_name(name) is None

    def test_the_prose_form_requires_the_word_effort(self):
        """Stated, not guessed: away from the end of the name, `Max` alone is not.

        The word `Effort` is what makes AA's prose an explicit statement. Without
        it the level would have to be inferred from a bare parenthetical, and
        inferring a level is the thing this project refuses everywhere else.

        Note the contrast with the terse dialect, which needs no such word: a
        *trailing* `"(Max)"` is read, because a trailing parenthetical is itself
        the statement. Only the mid-name, effort-less form is refused.
        """
        assert effort_from_name("Some Model (Adaptive Reasoning, Max, Default Fallback)") is None
        # Trailing forms are still read, with or without the word.
        assert effort_from_name("Some Model (Adaptive Reasoning, Max)") == "max"

    def test_it_reports_what_the_name_states_not_what_the_model_is(self):
        """The contract, pinned so it is not reused as an effort oracle.

        `"Qwen3.8 Max"` is a product name whose last word collides with Anthropic's
        `max` level. This reader reports `max` because that is what the name says.
        The caller guards against acting on it -- see
        `test_matching.TestAaStatedEffortSlugRung::test_a_product_name_containing_an_effort_word_does_not_construct_a_key`.
        """
        assert effort_from_name("Qwen3.8 Max") == "max"


class TestHarnessFold:
    def test_strips_known_harness_suffix(self):
        assert harness_fold("gpt-5-6-sol-xhigh-codex-harness") == (
            "gpt-5-6-sol-xhigh",
            "codex-harness",
        )

    @pytest.mark.parametrize(
        "key",
        [
            "claude-opus-5-high",  # effort token -- never folded
            "gpt-5-5-xhigh",
            "gpt-5-5",
            "",
            "codex-harness",  # nothing left after stripping
        ],
    )
    def test_refuses_everything_else(self, key):
        assert harness_fold(key) is None


def test_plus_sign_is_erased_and_collides():
    """DOCUMENTED LIMITATION, not desired behaviour.

    `+` is not alphanumeric, so it normalizes away: `"Command A+"` and
    `"Command A"` land on the *same* key even though Artificial Analysis
    publishes them as two distinct models with distinct slugs.

    Two consequences, both tolerated rather than fixed:

    * the unmatched ledger collapses the pair into one row, so a run can report
      615 rows for 616 unmatched records; and
    * if a LMArena `agent` entry ever normalizes to `command-a`, the `+` variant
      could claim it.

    Neither can produce a wrong match today -- neither record is in the agent
    set -- so this is recorded as a known limitation with an explicit example
    rather than patched with an invented `+` -> `plus` vocabulary.
    """
    assert normalize_model_key("Command A+") == normalize_model_key("Command A") == "command-a"
