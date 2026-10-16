"""The anti-fuzzy contract, pinned.

`docs/data-sources.md` §3 forbids similarity scoring, Levenshtein, substring and
prefix matching, and the model ladder's tests enforce that. This module matches
Hacker News prose against a curated vocabulary, which *sounds* like the thing
that rule forbids -- so the mechanism has to be exact, and the exactness has to be
tested rather than asserted in a docstring.

The two cases that carry the most weight are the ones that **do not match**:
``claude`` must not fire on ``claude-3-opus`` and ``gpt-5`` must not fire on
``gpt-5-mini``. Both are the shape of match a lenient matcher would produce, and
both are wrong. Their non-firing is the whole argument; the escape hatch is a
reviewed alias, which is what `TestVocabulary` guards the supply of.
"""

from __future__ import annotations

import pytest

from leaderboard.constants import (
    HN_ALIAS_WATCHLIST,
    HN_RELEVANCE_TERMS,
    HN_SWEEP_TERMS,
    MatchMode,
)
from leaderboard.hn_matching import (
    PhraseIndex,
    find_phrases,
    fired_relevance_terms,
    relevance_index,
)
from leaderboard.normalization import normalize_model_key


@pytest.fixture
def index() -> PhraseIndex:
    return PhraseIndex.build(
        [
            ("openai", MatchMode.WORD, "OpenAI"),
            ("anthropic", MatchMode.WORD, "Anthropic"),
            ("claude", MatchMode.WORD, "Claude"),
            ("cursor", MatchMode.WORD, "Cursor"),
            ("gpt-5", MatchMode.TOKEN_RUN, "GPT-5"),
            ("claude code", MatchMode.TOKEN_RUN, "Claude Code"),
            ("google deepmind", MatchMode.TOKEN_RUN, "Google DeepMind"),
            ("hugging face", MatchMode.TOKEN_RUN, "Hugging Face"),
        ]
    )


def keys(text: str, index: PhraseIndex) -> list[str]:
    return [match.key for match in find_phrases(text, index)]


class TestWordMode:
    def test_fires_on_a_bare_word(self, index):
        assert keys("I use openai daily", index) == ["openai"]

    def test_is_case_insensitive(self, index):
        assert keys("OPENAI", index) == ["openai"]
        assert keys("OpenAI", index) == ["openai"]

    def test_fires_on_a_possessive(self, index):
        """`OpenAI's` splits into `OpenAI` and `s`, which is why the apostrophe is
        a word separator and not part of the token."""
        assert keys("OpenAI's API is good", index) == ["openai"]

    def test_does_not_fire_inside_a_longer_word(self, index):
        """The load-bearing negative. A substring matcher would fire here; the fix
        is a reviewed alias for `openai-compatible`, not a looser rule."""
        assert keys("openai-compatible servers", index) == []
        assert keys("openaisdk", index) == []

    def test_does_not_match_a_longer_model_name(self, index):
        """`claude` must not tag every Claude-3 thread as the Claude service."""
        assert keys("claude-3-opus is old", index) == []
        assert keys("claude-2.1 was released", index) == []

    def test_fires_when_the_word_stands_alone(self, index):
        assert keys("Claude is good", index) == ["claude"]


class TestTokenRunMode:
    def test_fires_on_the_exact_token_run(self, index):
        assert keys("the GPT-5 release", index) == ["gpt-5"]

    def test_does_not_match_a_longer_token_run(self, index):
        """The second load-bearing negative: a proper sub-run is not a match, so
        `gpt-5` cannot silently claim `gpt-5-mini`'s numbers."""
        assert keys("GPT-5-mini is cheap", index) == []
        assert keys("GPT-5.5 is newer", index) == []

    def test_matches_a_multi_word_spelling(self, index):
        assert keys("Google DeepMind announced it", index) == ["google-deepmind"]

    def test_matches_the_hyphenated_spelling_of_the_same_phrase(self, index):
        """Both spellings normalize to one key, so one alias covers both."""
        assert keys("google-deepmind announced it", index) == ["google-deepmind"]

    def test_matches_a_hyphenated_and_spaced_phrase_alike(self, index):
        assert keys("Hugging Face and hugging-face", index) == ["hugging-face"]

    def test_a_multi_word_phrase_will_not_span_unrelated_words(self, index):
        """The words have to be adjacent, or `hugging` in one clause would join
        `face` in the next."""
        assert keys("hugging a cat's face", index) == []


class TestTokenPrefixMode:
    """The mode that keeps the vocabulary a list of subjects, not of versions.

    Without it `gpt` does not fire on "GPT-5" at all -- the token run is `gpt-5`,
    which is not the word `gpt` -- so a thread titled "GPT-5 released" would fire
    no relevance term, never enter the bank, and be invisible to the feature.
    """

    @pytest.fixture
    def prefix(self) -> PhraseIndex:
        return PhraseIndex.build(
            [
                ("gpt", MatchMode.TOKEN_PREFIX, "GPT"),
                ("llama", MatchMode.TOKEN_PREFIX, "Llama"),
                ("rag", MatchMode.TOKEN_PREFIX, "RAG"),
                ("phi", MatchMode.TOKEN_PREFIX, "Phi"),
                ("qwen", MatchMode.TOKEN_PREFIX, "Qwen"),
                ("grok", MatchMode.TOKEN_PREFIX, "Grok"),
            ]
        )

    @pytest.mark.parametrize("text", ["GPT-5", "GPT-5-mini", "GPT-4o", "gpt-5.5"])
    def test_reaches_every_version_of_the_stem(self, prefix, text):
        assert keys(text, prefix) == ["gpt"]

    def test_reaches_the_bare_stem_too(self, prefix):
        """An exact match is accepted for every mode, so the stem itself counts."""
        assert keys("gpt is good", prefix) == ["gpt"]

    @pytest.mark.parametrize("text", ["llama-3-8b", "llama.cpp"])
    def test_reaches_multi_token_versions(self, prefix, text):
        assert keys(text, prefix) == ["llama"]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # A version digit written flush against the name is part of the same
            # word, so there is no token boundary for the rule above to find.
            ("Qwen3 vs Llama 4", {"qwen", "llama"}),
            ("Qwen2.5 is out", {"qwen"}),
            ("Llama3 release", {"llama"}),
            ("GPT4o pricing", {"gpt"}),
            ("phi3 mini", {"phi"}),
            ("grok3", {"grok"}),
        ],
    )
    def test_reaches_a_version_number_written_without_a_separator(self, prefix, text, expected):
        """Required rather than a nicety: the project's own normalized model keys
        use this form (`qwen3-8-flash-next`), so a matcher that could not read
        "Qwen3" would fail on the spelling LMArena publishes."""
        assert set(keys(text, prefix)) == expected

    @pytest.mark.parametrize("text", ["qwenly", "gptx", "llamas", "ragtime"])
    def test_a_flush_remainder_must_begin_with_a_digit(self, prefix, text):
        """This is what keeps the version rule from becoming a general prefix rule.
        A *letter* written flush against the stem makes a different word, not a
        version -- `ragtime` is not about retrieval-augmented generation.
        """
        assert keys(text, prefix) == []

    def test_a_hyphen_after_the_stem_is_an_ordinary_token_boundary(self, prefix):
        """Not an exception: `phi-loso` has a real token boundary, so the
        token-run rule applies exactly as it does for `google-deepmind`. What the
        version rule adds is the case with *no* separator at all."""
        assert keys("phi-loso", prefix) == ["phi"]

    def test_a_multi_token_alias_also_reaches_a_flush_version(self):
        index = PhraseIndex.build([("claude-code", MatchMode.TOKEN_PREFIX, "Claude Code")])
        assert keys("claude-code2", index) == ["claude-code"]

    @pytest.mark.parametrize("text", ["gptx", "philosophy", "rage", "llamaindex"])
    def test_never_matches_inside_a_word(self, prefix, text):
        """A *token*-level prefix, never a character-level one. This is what makes
        writing a vendor stem down safe: `rag` cannot reach "rage"."""
        assert keys(text, prefix) == []

    @pytest.mark.parametrize("text", ["rag-pipeline", "phi-3"])
    def test_reaches_a_hyphenated_compound(self, prefix, text):
        assert keys(text, prefix) == [text.split("-")[0]]

    @pytest.mark.parametrize("text", ["mini-gpt", "not-rag", "my-phi"])
    def test_matches_a_leading_run_only_not_a_trailing_one(self, prefix, text):
        """Prefix means *leading*: the stem has to open the token run. Without
        this, `gpt` would tag every compound that happens to end in it."""
        assert keys(text, prefix) == []

    def test_a_bare_stem_between_other_words_still_fires(self, prefix):
        """Not an exception to the rule above -- a lone word *is* a leading run of
        length one, and exact matching is accepted for every mode."""
        assert keys("the rag tag bunch", prefix) == ["rag"]

    def test_the_longest_candidate_wins(self):
        """So a two-token alias is preferred over a one-token alias it contains."""
        index = PhraseIndex.build(
            [
                ("meta", MatchMode.TOKEN_PREFIX, "Meta"),
                ("meta-llama", MatchMode.TOKEN_PREFIX, "Meta Llama"),
            ]
        )
        assert keys("meta-llama-3", index) == ["meta-llama"]
        assert keys("meta-analysis", index) == ["meta"]

    def test_a_word_alias_does_not_gain_prefix_behaviour(self, index):
        """`word` stays whole-word: only an explicit `token_prefix` alias reaches
        a longer token run."""
        assert keys("openai-compatible", index) == []
        assert keys("cursor-ide", index) == []

    def test_a_token_run_alias_does_not_gain_prefix_behaviour(self, index):
        """The protection the plan cared about: `gpt-5` must not inherit
        "GPT-5-mini" merely because a prefix mode exists somewhere."""
        assert keys("GPT-5-mini", index) == []

    def test_mentions_accumulate_across_different_versions(self, prefix):
        """Keyed on the phrase, so "GPT-4" and "GPT-5" count as two mentions of
        one term rather than two separate terms."""
        matches = find_phrases("GPT-4 and GPT-5", prefix)
        assert [(match.key, match.mentions) for match in matches] == [("gpt", 2)]

    def test_the_exemplar_is_the_word_that_fired(self, prefix):
        assert find_phrases("see GPT-5-mini", prefix)[0].matched_text == "GPT-5-mini"


class TestOverlaps:
    def test_a_phrase_can_fire_alongside_a_shorter_one_it_contains(self, index):
        """Both tags are true, and a thread about Claude Code is also about Claude."""
        assert keys("I use Claude Code daily", index) == ["claude", "claude-code"]

    def test_reports_every_occurrence_as_a_mention_count(self, index):
        matches = find_phrases("openai and openai again", index)
        assert [(match.key, match.mentions) for match in matches] == [("openai", 2)]

    def test_results_are_ordered_by_mentions_then_key(self, index):
        matches = find_phrases("cursor cursor openai", index)
        assert [match.key for match in matches] == ["cursor", "openai"]


class TestProvenance:
    def test_reports_the_verbatim_text_that_fired(self, index):
        """A reviewer asking "why is this tagged Anthropic?" needs the string, not
        the normalized key."""
        match = find_phrases("OpenAI's API", index)[0]
        assert match.matched_text == "OpenAI"
        assert match.key == "openai"

    def test_reports_the_verbatim_multi_word_span(self, index):
        match = find_phrases("see Google DeepMind's post", index)[0]
        assert match.matched_text == "Google DeepMind"

    def test_reports_the_mode_that_let_it_fire(self, index):
        assert find_phrases("openai", index)[0].mode == MatchMode.WORD
        assert find_phrases("gpt-5", index)[0].mode == MatchMode.TOKEN_RUN


class TestIndexConstruction:
    def test_skips_an_entry_that_normalizes_to_nothing(self):
        built = PhraseIndex.build([("!!!", MatchMode.WORD, "!!!")])
        assert len(built) == 0

    def test_keeps_the_first_entry_for_a_duplicated_key(self):
        """Otherwise the outcome would depend on row order. The two entries differ
        in mode so the winner is observable: `matched_text` is the source span, so
        it cannot show which alias's declaration won."""
        built = PhraseIndex.build(
            [
                ("openai", MatchMode.TOKEN_RUN, "OpenAI"),
                ("openai", MatchMode.WORD, "openai"),
            ]
        )
        assert len(built) == 1
        assert find_phrases("openai", built)[0].mode == MatchMode.TOKEN_RUN

    def test_max_width_follows_the_widest_phrase(self):
        built = PhraseIndex.build([("retrieval augmented generation", MatchMode.TOKEN_RUN, "retrieval augmented generation")])
        assert built.max_width == 3

    def test_an_empty_index_matches_nothing(self):
        assert find_phrases("anything at all", PhraseIndex.build([])) == []

    @pytest.mark.parametrize("text", [None, "", "   "])
    def test_blank_text_matches_nothing(self, index, text):
        assert find_phrases(text, index) == []

    def test_punctuation_only_text_matches_nothing(self, index):
        assert find_phrases("-- ... !!", index) == []


class TestRelevance:
    @pytest.fixture
    def relevance(self) -> PhraseIndex:
        return relevance_index(HN_RELEVANCE_TERMS)

    @pytest.mark.parametrize(
        "title",
        [
            "Show HN: I built an LLM agent in Rust",
            "Muse Spark Open (meta.ai)",
            "Why transformers scale",
            "Ask HN: Is Cursor worth it?",
            "Fine-tuning Llama on a single GPU",
        ],
    )
    def test_an_llm_story_fires_at_least_one_term(self, relevance, title):
        assert fired_relevance_terms(title=title, index=relevance)

    @pytest.mark.parametrize(
        "title",
        [
            "Ask HN: best laptop 2026",
            "A deep dive into Postgres indexes",
            "Show HN: my static site generator",
        ],
    )
    def test_an_unrelated_story_fires_nothing(self, relevance, title):
        assert fired_relevance_terms(title=title, index=relevance) == []

    def test_the_domain_counts_as_evidence(self, relevance):
        """A story linking to a vendor's site is about that vendor."""
        assert fired_relevance_terms(title="Launch", domain="openai.com", index=relevance) == [
            "openai"
        ]

    @pytest.mark.parametrize(
        ("domain", "expected"),
        [
            ("openai.com", "openai"),
            ("www.anthropic.com", "anthropic"),
            ("dev.meta.ai", "meta-ai"),
            ("huggingface.co", "huggingface"),
        ],
    )
    def test_domain_labels_are_matched_separately(self, relevance, domain, expected):
        """A hostname's dots are label separators, not part of a name -- without
        splitting them, `openai.com` is one word and fires nothing."""
        assert expected in fired_relevance_terms(title="Launch", domain=domain, index=relevance)

    def test_a_title_keeps_its_dots_so_versions_do_not_over_match(self, relevance):
        """The counterpart to the domain rule: `GPT-5.5` stays one word rather than
        tokenizing as `GPT-5` plus `5`. That is what stops an *exact* alias like
        `gpt-5` from claiming it -- see
        `TestTokenRunMode::test_does_not_match_a_longer_token_run`. Both spellings
        here still reach the `gpt` subject, which is the intended breadth."""
        assert fired_relevance_terms(title="GPT-5.5 vs GPT-5", index=relevance) == ["gpt"]

    def test_terms_are_returned_normalized_and_sorted(self, relevance):
        fired = fired_relevance_terms(title="Hugging Face and LLM agents", index=relevance)
        assert fired == sorted(fired)
        assert "hugging-face" in fired

    def test_no_stemming_is_applied(self, relevance):
        """Deliberate and unavoidable: a token-level prefix cannot reach an
        inflection, because `llms` is one token rather than `llm` plus `s`. Both
        spellings are listed instead, so every match is a human's choice."""
        assert "llm" in HN_RELEVANCE_TERMS
        assert "llms" in HN_RELEVANCE_TERMS
        assert fired_relevance_terms(title="llms", index=relevance) == ["llms"]

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("GPT-5 released", "gpt"),
            ("Claude 3.5 Sonnet is here", "claude"),
            ("Llama 4 benchmarks", "llama"),
            ("Gemini 2.0 Flash", "gemini"),
        ],
    )
    def test_prefixed_versions_fire_their_subject(self, relevance, title, expected):
        """The case the feature depends on: a versioned title has to be recognised
        as LLM-related, or the thread never enters the bank."""
        assert expected in fired_relevance_terms(title=title, index=relevance)

    def test_a_versioned_title_is_not_dropped(self, relevance):
        assert fired_relevance_terms(title="GPT-5 released", index=relevance) != []


class TestVocabulary:
    """Invariants on the curated lists, which are configuration and can drift."""

    @pytest.mark.parametrize("term", HN_RELEVANCE_TERMS)
    def test_every_term_normalizes_to_something(self, term):
        assert normalize_model_key(term)

    def test_no_two_terms_share_a_normalized_key(self):
        """A duplicate is a typo that would make one line dead configuration."""
        keys = [normalize_model_key(term) for term in HN_RELEVANCE_TERMS]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        assert duplicates == []

    def test_the_sweep_list_is_a_subset_of_the_relevance_list(self):
        """A swept term that is not a relevance term would fetch stories the local
        filter then discards -- requests spent for nothing."""
        assert set(HN_SWEEP_TERMS) <= set(HN_RELEVANCE_TERMS)

    def test_the_sweep_list_is_shorter_than_the_relevance_list(self):
        """Every swept term costs a request per sweep, so it is a shortlist."""
        assert len(HN_SWEEP_TERMS) < len(HN_RELEVANCE_TERMS)

    def test_unique_sweep_terms(self):
        assert len(set(HN_SWEEP_TERMS)) == len(HN_SWEEP_TERMS)

    def test_watchlist_stems_are_non_empty(self):
        assert all(normalize_model_key(stem) for stem in HN_ALIAS_WATCHLIST)

    def test_an_alias_for_every_watchlist_stem_is_a_valid_word_phrase(self):
        """The watchlist exists because these stems do *not* match compounds, so
        they must at least be spellable as a word-mode alias."""
        index = PhraseIndex.build(
            (stem, MatchMode.WORD, stem) for stem in HN_ALIAS_WATCHLIST
        )
        for stem in HN_ALIAS_WATCHLIST:
            assert find_phrases(f"I like {stem} a lot", index), stem
