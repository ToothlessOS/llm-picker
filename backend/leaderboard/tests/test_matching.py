"""The match ladder.

Two properties matter more than coverage here:

1. **It never guesses.** Every refusal below is a case where a plausible-looking
   match exists and the ladder declines it. Those tests are the point of the
   module.
2. **Rung order is a correctness property.** The AA ladder prefers `name` over
   `slug` because a bare slug can denote a *different reasoning level* than the
   record's own name. Getting this backwards is silent: it produces a match that
   looks right, scores well on coverage, and attributes one model's benchmark
   numbers to another.
"""

from __future__ import annotations

import pytest

from leaderboard.constants import MatchMethod, Source
from leaderboard.matching import (
    AliasTable,
    Claim,
    MatchIndex,
    dedupe_by_model_key,
    match_aa_model,
    match_lmarena_key,
    resolve_collisions,
)
from leaderboard.tests.factories import Row, agent_index, webdev


# --------------------------------------------------------------------------- #
# Ladder 2: Artificial Analysis -> agent
# --------------------------------------------------------------------------- #


class TestAaRungOrder:
    """The reasoning-level trap, as a regression test."""

    def test_name_wins_over_slug_when_name_states_effort(self):
        """The exact trap this design was corrected to avoid.

        AA publishes `slug="gpt-5-5"` with `name="GPT-5.5 (xhigh)"`. The agent
        split contains *both* `GPT 5.5` and `GPT 5.5 (xHigh)`. Keying on the slug
        first attaches the **xhigh** record to the **base** model -- a wrong
        answer that is indistinguishable from a right one downstream.
        """
        index = agent_index("GPT 5.5", "GPT 5.5 (xHigh)")

        outcome = match_aa_model(index, name="GPT-5.5 (xhigh)", slug="gpt-5-5")

        assert outcome.is_match
        assert outcome.method == MatchMethod.EXACT_NAME.value
        assert outcome.matched_key == "gpt-5-5-xhigh"
        assert outcome.target.model_name == "GPT 5.5 (xHigh)"

    def test_slug_rung_is_skipped_entirely_when_name_states_effort(self):
        """When the name names an effort level, a slug miss must not fall through.

        The slug rung is not merely deprioritised -- it is not consulted, because
        a bare slug beside an effort-stating name is exactly the ambiguous shape.
        """
        index = agent_index("GPT 5.5")  # only the base, no xhigh sibling

        outcome = match_aa_model(index, name="GPT-5.5 (xhigh)", slug="gpt-5-5")

        assert not outcome.is_match
        assert outcome.detail["name_states_effort"] is True
        assert outcome.detail["slug_rung_skipped"] is True

    def test_slug_rung_is_used_when_the_name_is_silent_about_effort(self):
        """Where the name carries no effort marker, the slug is safe and needed.

        This is the real Claude-family shape: AA spells effort out in prose
        (`"Claude Opus 5 (Adaptive Reasoning, High Effort)"`), which the marker
        check does not recognise, so the slug is what resolves it.
        """
        index = agent_index("Claude Opus 5 (High)")

        outcome = match_aa_model(
            index,
            name="Claude Opus 5 (Adaptive Reasoning, High Effort)",
            slug="claude-opus-5-high",
        )

        assert outcome.is_match
        assert outcome.method == MatchMethod.EXACT_SLUG.value
        assert outcome.matched_key == "claude-opus-5-high"

    def test_never_infers_a_different_effort_level(self):
        """A variant with no same-effort counterpart must stay unmatched.

        AA publishes `claude-opus-4-8` at Max effort only; LMArena's agent split
        has `Claude Opus 4.8 (High)`. Attaching the Max numbers to the High entry
        would be a confident wrong answer, so the ladder reports instead.
        """
        index = agent_index("Claude Opus 4.8 (High)")

        outcome = match_aa_model(
            index,
            name="Claude Opus 4.8 (Adaptive Reasoning, Max Effort)",
            slug="claude-opus-4-8",
        )

        assert not outcome.is_match


class TestAaAntiFuzzy:
    """Near misses must not match. The whole point of dropping fuzzy scoring.

    Each input below is a *plausible* neighbour of something in the index --
    its prefix, its sibling, or a neighbouring release -- and must be refused.
    A fuzzy matcher would happily link every one of them.
    """

    #: The agent entries a real refresh would have loaded.
    PRESENT = ("GPT 5 mini", "GPT 5.1 Codex", "GPT 4o", "Claude Opus 5 (High)")

    @pytest.mark.parametrize(
        ("name", "slug"),
        [
            ("GPT-5", "gpt-5"),  # prefix of gpt-5-mini
            ("GPT-5.2 Codex", "gpt-5-2-codex"),  # neighbouring release
            ("GPT-4o mini", "gpt-4o-mini"),  # sibling of gpt-4o
            ("GPT 5", "gpt-5"),
            ("Claude Opus", "claude-opus"),  # prefix of claude-opus-5-high
            ("Claude Opus 5", "claude-opus-5"),  # parent of the effort levels
        ],
    )
    def test_does_not_match_a_different_model(self, name, slug):
        index = agent_index(*self.PRESENT)

        assert not match_aa_model(index, name=name, slug=slug).is_match

    def test_an_exact_neighbour_still_matches(self):
        """The inverse guard: the refusals above must not be blanket refusals."""
        index = agent_index(*self.PRESENT)

        assert match_aa_model(index, name="GPT-5 mini", slug="gpt-5-mini").is_match


class TestAliasOverride:
    def test_alias_wins_over_every_inference_rung(self):
        """A human decision beats anything the ladder would have concluded."""
        index = agent_index("Claude Opus 5 (Max)", "Claude Opus 5 (High)")
        table = AliasTable()
        table.add(
            Source.ARTIFICIAL_ANALYSIS.value,
            "agent",
            "Claude Opus 5 (Adaptive Reasoning, Max Effort)",
            "claude-opus-5-max",
        )

        outcome = match_aa_model(
            index,
            name="Claude Opus 5 (Adaptive Reasoning, Max Effort)",
            slug="claude-opus-5-high",  # would resolve elsewhere if consulted
            alias_table=table,
        )

        assert outcome.is_match
        assert outcome.method == MatchMethod.ALIAS.value
        assert outcome.matched_key == "claude-opus-5-max"

    def test_alias_target_absent_is_surfaced_not_silently_dropped(self):
        """A stale alias is a real, fixable problem -- say so."""
        index = agent_index("Claude Opus 5 (High)")
        table = AliasTable()
        table.add(Source.ARTIFICIAL_ANALYSIS.value, "agent", "Some Model", "key-that-left")

        outcome = match_aa_model(index, name="Some Model", slug="some-model", alias_table=table)

        assert not outcome.is_match
        assert outcome.detail["alias_target_absent"] is True


# --------------------------------------------------------------------------- #
# Ladder 1: LMArena category -> agent
# --------------------------------------------------------------------------- #


class TestCategoryLadder:
    def test_display_name_joins_to_slug_spelling(self):
        """The cross-category join that normalization exists to enable."""
        index = agent_index("Claude Opus 5 (High)")

        outcome = match_lmarena_key(index, "claude-opus-5-high", category="document")

        assert outcome.is_match
        assert outcome.method == MatchMethod.EXACT_KEY.value

    def test_ambiguous_exact_match_refuses(self):
        """Two agent rows on one key is a genuine ambiguity, not last-one-wins."""
        index = MatchIndex()
        index.add("dupe-model", Row(category="agent", model_name="Dupe Model"))
        index.add("dupe-model", Row(category="agent", model_name="DUPE  Model"))

        outcome = match_lmarena_key(index, "dupe-model", category="webdev")

        assert outcome.status == "ambiguous"
        assert not outcome.is_match

    def test_harness_wrapper_folds_to_the_underlying_model(self):
        """The one relaxation, and the real case it was added for."""
        index = agent_index("GPT 5.6 Sol (xHigh)")

        outcome = match_lmarena_key(index, "gpt-5.6-sol-xhigh (codex-harness)", category="webdev")

        assert outcome.is_match
        assert outcome.method == MatchMethod.HARNESS_FOLD.value
        assert outcome.matched_key == "gpt-5-6-sol-xhigh"
        assert outcome.detail["stripped"] == "codex-harness"

    def test_fold_refuses_when_the_target_is_shadowed(self):
        """The real refusal, taken from live data.

        `gpt-5.5 (codex-harness)` folds to `gpt-5-5`, but the agent index also
        holds `gpt-5-5-xhigh`. Which one the harness wrapper actually wrapped is
        unknowable, and one of the two answers would attach the wrong effort
        level's scores. Refuse and report.
        """
        index = agent_index("GPT 5.5", "GPT 5.5 (xHigh)")

        outcome = match_lmarena_key(index, "gpt-5.5 (codex-harness)", category="webdev")

        assert outcome.status == "ambiguous"
        assert outcome.detail["stripped"] == "codex-harness"
        assert outcome.detail["shadowed_by"] == ["gpt-5-5-xhigh"]

    def test_fold_refuses_on_multiple_candidates(self):
        index = MatchIndex()
        index.add("target", Row(category="agent", model_name="Target"))
        index.add("target", Row(category="agent", model_name="TARGET"))

        outcome = match_lmarena_key(index, "target-codex-harness", category="webdev")

        assert outcome.status == "ambiguous"

    def test_effort_tokens_are_never_folded(self):
        """The regression guard for the wrong design.

        An earlier draft folded effort words, which made `gpt-5.5-high` match
        `"GPT 5.5"`. It must not: `"GPT 5.5 (xHigh)"` is the true sibling, and
        the fold produced zero correct matches on real data.
        """
        index = agent_index("GPT 5.5", "GPT 5.5 (xHigh)")

        outcome = match_lmarena_key(index, "gpt-5.5-high", category="webdev")

        assert not outcome.is_match


# --------------------------------------------------------------------------- #
# Dedupe
# --------------------------------------------------------------------------- #


class TestDedupe:
    def test_collapses_the_real_webdev_rank_conflict(self):
        """`claude-opus-5-max` really does appear at ranks 3, 1, 3, 2 and 3.

        Without dedupe the `(category, model_key)` constraint refuses the write,
        so the first successful refresh would also be the last.
        """
        rows = [
            webdev("claude-opus-5-max", 3),
            webdev("claude-opus-5-max", 1),
            webdev("claude-opus-5-max", 3),
            webdev("claude-opus-5-max", 2),
        ]

        winners, losers = dedupe_by_model_key(rows)

        assert len(winners) == 1
        assert winners[0].rank == 1
        assert len(losers) == 3
        assert {loser.rank for loser, _ in losers} == {2, 3}

    def test_is_stable_across_runs(self):
        """Two identical refreshes must not flip which row wins."""
        rows = [
            webdev("model-b", 2),
            Row(category="webdev", model_name="Model  B", rank=2),
        ]

        first = dedupe_by_model_key(rows)[0][0].model_name
        second = dedupe_by_model_key(list(reversed(rows)))[0][0].model_name

        assert first == second

    def test_keeps_distinct_models_apart(self):
        rows = [webdev("gpt-5-5", 1), webdev("gpt-5-5-xhigh", 2)]

        winners, losers = dedupe_by_model_key(rows)

        assert len(winners) == 2
        assert losers == []

    def test_preserves_every_row_either_as_winner_or_loser(self):
        """Nothing is dropped silently -- that is the ledger's whole premise."""
        rows = [webdev("a-model", 1), webdev("a-model", 2), webdev("b-model", 3)]

        winners, losers = dedupe_by_model_key(rows)

        assert len(winners) + len(losers) == len(rows)


class TestResolveCollisions:
    @staticmethod
    def claim(slug: str, method: str, key: str = "shared-key") -> Claim:
        return Claim(
            matched_key=key,
            method=method,
            model=object(),
            name=slug.replace("-", " ").title(),
            slug=slug,
        )

    def test_alias_beats_every_inferred_method(self):
        claims = [
            self.claim("exact-name-record", MatchMethod.EXACT_NAME.value),
            self.claim("aliased", MatchMethod.ALIAS.value),
        ]

        winners, losers = resolve_collisions(claims)

        assert winners["shared-key"].method == MatchMethod.ALIAS.value
        assert len(losers) == 1

    def test_prefers_the_record_whose_own_slug_is_the_key(self):
        """A slug that *is* the key is the strongest non-human evidence."""
        claims = [
            self.claim("exact-name-record", MatchMethod.EXACT_NAME.value),
            self.claim("shared-key", MatchMethod.EXACT_SLUG.value),
        ]

        winners, _ = resolve_collisions(claims)

        assert winners["shared-key"].slug == "shared-key"

    def test_is_deterministic_regardless_of_input_order(self):
        claims = [
            self.claim("b-record", MatchMethod.EXACT_NAME.value),
            self.claim("a-record", MatchMethod.EXACT_NAME.value),
        ]

        forward, _ = resolve_collisions(claims)
        backward, _ = resolve_collisions(list(reversed(claims)))

        assert forward["shared-key"].slug == backward["shared-key"].slug

    def test_every_loser_is_returned(self):
        claims = [
            self.claim("one", MatchMethod.EXACT_NAME.value),
            self.claim("two", MatchMethod.EXACT_SLUG.value),
            self.claim("three", MatchMethod.HARNESS_FOLD.value),
        ]

        winners, losers = resolve_collisions(claims)

        assert len(winners) == 1
        assert len(losers) == 2
