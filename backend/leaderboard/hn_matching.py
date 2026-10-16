"""Match free text against curated vocabularies, exactly.

**Why this module is allowed to exist.** `docs/data-sources.md` §3 forbids
similarity scoring, Levenshtein, substring and prefix matching for the model
ladder, and the tests enforce it. Matching Hacker News prose to a vocabulary is
unavoidably a text-to-vocabulary problem, so the resolution is a **scoping
argument backed by exact mechanics** rather than a relaxation of that rule:

    This module matches free text against a vocabulary a human wrote. It produces
    advisory display tags on Hacker News content. It never produces a
    `ModelMatch`, never influences `/overview/`, `/models/{key}/` or
    `/unmatched/`, and never feeds the ladder. The ladder compares *two records
    the sources state*; this compares *a string against a table a human wrote*.
    No scoring exists in either.

**Exact means exact.** Three modes, and none of them scores anything:

``word``
    The phrase matches one whole word. ``openai`` fires on ``"OpenAI's API"`` and
    on ``"openai"``, and does **not** fire on ``"openai-compatible"``.
``token_run``
    The phrase's tokens equal the whole hyphen-joined token run of a word, or of
    a run of consecutive words. ``gpt-5`` fires on ``"GPT-5"`` and **not** on
    ``"GPT-5-mini"``; ``google deepmind`` fires on ``"Google DeepMind"``.
``token_prefix``
    The phrase's tokens are a *leading, complete* token sequence of a single
    word. ``gpt`` fires on ``"GPT-5"`` and ``"GPT-5-mini"``; ``rag`` fires on
    ``"rag-pipeline"`` and not on ``"rage"``.

**Why the third mode earns its place.** Without it ``gpt`` does not fire on
``"GPT-5"`` -- the token run is ``gpt-5``, which is not the word ``gpt`` -- so a
thread entitled *GPT-5 released* would fire no relevance term at all, never enter
the bank, and be invisible to the whole feature. Enumerating every version in the
vocabulary instead is an unbounded list that goes stale with each release.

The mode is a **token**-level prefix and never a character-level one: the alias's
tokens must be a leading *complete* token sequence, so ``rag`` cannot reach
``"rage"`` and ``phi`` cannot reach ``"philosophy"``. It is for vendor and service
stems -- ``gpt``, ``claude``, ``llama`` -- and *not* for model variants. Marking
``gpt-5`` as a prefix is precisely how ``"GPT-5-mini"`` would wrongly inherit
GPT-5's identity; that stays a rule a reviewer keeps, because the mode is
per-alias and visible in the admin for exactly that reason.

A consequence that is deliberate rather than unfortunate: ``claude`` in
``word`` mode does **not** match ``"claude-3-opus"``. A reviewer who wants that
writes it as ``token_prefix``, which is a decision they make and can be reviewed
-- rather than a prefix rule that quietly applies to everything, including
``gpt-5`` against ``gpt-5-mini``.

Note also that a token-level prefix cannot do stemming: ``llms`` is one token,
not ``llm`` plus ``s``, so ``llm`` does not reach it. Inflected spellings are
listed explicitly in the vocabulary, which keeps every match a human's choice.

Everything here is a pure function of its arguments. No database, no network, no
settings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from .constants import MatchMode
from .normalization import normalize_model_key

#: A word is a run of alphanumerics with internal ``+``/``#``/``.``/``-`` --
#: which is what makes ``GPT-5``, ``claude-3-opus`` and ``C++`` single words while
#: ``OpenAI's`` splits into ``OpenAI`` and ``s``. Splitting on the apostrophe is
#: the point: it is what lets ``openai`` fire on a possessive. A trailing
#: separator is tolerated and then normalized away.
_WORD = re.compile(r"[A-Za-z0-9]+(?:[+#.\-][A-Za-z0-9]*)*")


@dataclass(frozen=True)
class Phrase:
    """One vocabulary entry.

    ``key`` is the normalized form that matching compares against; ``text`` is the
    verbatim spelling, used only for reporting what was observed.
    """

    key: str
    mode: str
    #: Whitespace-separated word count, which bounds how many consecutive words a
    #: candidate window may span.
    width: int


@dataclass(frozen=True)
class PhraseIndex:
    """A vocabulary, indexed for whole-word lookup.

    Built once per run and reused for every thread, because the scan below is the
    inner loop of ingestion.
    """

    phrases: Mapping[str, Phrase]

    @property
    def max_width(self) -> int:
        """The widest phrase, so the scan knows how far to look ahead."""
        return max((phrase.width for phrase in self.phrases.values()), default=1)

    def __len__(self) -> int:
        return len(self.phrases)

    @classmethod
    def build(cls, entries: Iterable[tuple[str, str, str]]) -> PhraseIndex:
        """Index ``(key, mode, text)`` triples.

        Later entries do not overwrite earlier ones for the same key: the caller
        supplies a vocabulary whose keys are already unique, and silently
        replacing one would make the outcome depend on row order.
        """
        phrases: dict[str, Phrase] = {}
        for key, mode, text in entries:
            normalized = normalize_model_key(key)
            if not normalized or normalized in phrases:
                continue
            width = max(1, len(str(text).split()))
            phrases[normalized] = Phrase(key=normalized, mode=mode, width=width)
        return cls(phrases=phrases)


@dataclass(frozen=True)
class PhraseMatch:
    """One firing: which phrase, the exact text that fired, and how often."""

    key: str
    mode: str
    matched_text: str
    mentions: int


def find_phrases(text: object, index: PhraseIndex) -> list[PhraseMatch]:
    """Every phrase in ``index`` that fires in ``text``, exactly.

    Windows of consecutive words are tried from one word up to the vocabulary's
    widest phrase. A window matches when its tokens equal the phrase's key
    *exactly* -- with two restrictions that are the whole of the mode system:

    * a ``word`` phrase fires only on a single-word window, so it cannot span
      unrelated words;
    * a ``token_prefix`` phrase fires on a single word whose token run *starts*
      with the phrase's tokens and continues past them.

    An exact whole-window match is accepted for every mode, so a ``token_prefix``
    alias still matches its own verbatim spelling.
    """
    if not text or not index.phrases:
        return []

    source = str(text)
    words = _tokenize(source)
    if not words:
        return []

    max_width = index.max_width
    totals: dict[str, int] = {}
    exemplars: dict[str, str] = {}
    modes: dict[str, str] = {}

    for start in range(len(words)):
        for width in range(1, max_width + 1):
            end = start + width
            if end > len(words):
                break
            joined = "-".join(word.key for word in words[start:end])
            phrase = _phrase_for(joined, width, index)
            if phrase is None:
                continue

            # Keyed on the *phrase*, not the matched word: a relevance term wants
            # `gpt` whether the text said "GPT-5" or "GPT-5-mini", so both
            # occurrences count toward one term rather than two.
            key = phrase.key
            totals[key] = totals.get(key, 0) + 1
            if key not in exemplars:
                modes[key] = phrase.mode
                # The verbatim span, not the normalized key: the tag has to be
                # able to show the reviewer the string that actually fired.
                exemplars[key] = source[words[start].start : words[end - 1].end]

    return [
        PhraseMatch(key=key, mode=modes[key], matched_text=exemplars[key], mentions=count)
        for key, count in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    ]


def _phrase_for(joined: str, width: int, index: PhraseIndex) -> Phrase | None:
    """The phrase a window of `width` words matches, or ``None``.

    An exact match is accepted for every mode. Beyond that, two restrictions --
    and they are the whole of the mode system:

    * ``word`` is refused on a window wider than one word, so it cannot span
      words that merely happen to sit next to each other;
    * ``token_prefix`` is offered only for single words, and only when the word
      carries at least one token past the alias.
    """
    phrase = index.phrases.get(joined)
    if phrase is not None:
        return None if phrase.mode == MatchMode.WORD and width > 1 else phrase
    return _prefix_hit(joined, index) if width == 1 else None


def _prefix_hit(word_key: str, index: PhraseIndex) -> Phrase | None:
    """The `token_prefix` phrase that leads this word's token run, if any.

    Two ways a phrase can lead a word, both exact:

    * **A whole leading token run.** The word's run begins with the phrase's whole
      run and carries at least one more token, so ``meta-llama-3`` is led by
      ``meta-llama``. Longest candidate first, so a two-token alias wins over a
      one-token alias it contains -- and ``rsplit`` with the *smaller* count is the
      longer prefix, which is the opposite of what the loop bound suggests.
    * **A leading run followed by a version number.** ``qwen3`` is led by ``qwen``
      even though there is no separator, because a version digit written flush
      against a name is part of the same word rather than a new token. This is not
      a general prefix rule: the remainder must *begin with a digit*, so ``phi``
      reaches ``phi-3`` and ``phi3`` but never ``philosophy``, and ``rag`` reaches
      ``rag-pipeline`` but never ``rage``.

    The second form is required rather than a nicety -- the project's own
    normalized model keys use it (`qwen3-8-flash-next`, `llama3-8b`), so a matcher
    that could not read *"Qwen3 vs Llama 4"* would fail on the very spelling
    LMArena publishes.
    """
    # A whole leading token run. `rsplit` with a smaller count strips fewer
    # separators, so position 1 is the longest prefix.
    for position in range(1, word_key.count("-") + 1):
        candidate = word_key.rsplit("-", position)[0]
        phrase = index.phrases.get(candidate)
        if phrase is not None and phrase.mode == MatchMode.TOKEN_PREFIX:
            return phrase

    # A version number written flush against the name. Candidates are generated by
    # cutting at each digit, which is O(length) lookups rather than a scan of the
    # vocabulary -- and a word with no digit in it produces none at all, so
    # `philosophy` cannot reach `phi`.
    for position, character in enumerate(word_key):
        if not character.isdigit():
            continue
        candidate = word_key[:position].rstrip("-")
        if not candidate:
            continue
        phrase = index.phrases.get(candidate)
        if phrase is not None and phrase.mode == MatchMode.TOKEN_PREFIX:
            return phrase

    return None


# --------------------------------------------------------------------------- #
# Relevance
# --------------------------------------------------------------------------- #


def relevance_index(terms: Iterable[str]) -> PhraseIndex:
    """A `PhraseIndex` over discovery terms.

    Terms are ``token_prefix``, which is the mode that makes the vocabulary
    affordable: ``gpt`` then reaches "GPT-5" and ``claude`` reaches
    "claude-3-opus", so the list stays a list of *subjects* rather than an
    ever-stale enumeration of every version and variant. It remains exact -- the
    alias has to be a leading complete token sequence -- so ``rag`` still does not
    reach "rage".

    A multi-word term is unaffected: ``hugging face`` is matched whole, since
    prefix mode applies only within a single word.
    """
    return PhraseIndex.build((term, MatchMode.TOKEN_PREFIX, term) for term in terms)


def fired_relevance_terms(
    *,
    title: object,
    domain: object = "",
    index: PhraseIndex,
) -> list[str]:
    """The relevance terms that fired for a story, normalized and sorted.

    The **title and link domain only** -- not the comment bodies. Relevance is
    decided at discovery time, before a thread's comments have been fetched, and
    a story that only becomes about LLMs three hundred comments deep is not what
    "LLM-related thread" means. Entity tagging does read the comments; that is a
    different question answered at a different stage.

    The domain's dots are turned into spaces first, because a hostname's dots are
    *label separators*, not part of a name. Without that, `openai.com` is a single
    word -- `.` has to stay a word character, or `GPT-5.5` would tokenize as
    `GPT-5` and wrongly fire the `gpt-5` term -- and no vendor domain would ever
    fire its own term.
    """
    parts = [str(title or "").strip(), str(domain or "").replace(".", " ").strip()]
    haystack = " ".join(part for part in parts if part)
    return sorted(match.key for match in find_phrases(haystack, index))


__all__ = [
    "Phrase",
    "PhraseIndex",
    "PhraseMatch",
    "find_phrases",
    "fired_relevance_terms",
    "relevance_index",
]


# --------------------------------------------------------------------------- #
# Tokenization
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Word:
    key: str
    start: int
    end: int


def _tokenize(text: str) -> list[_Word]:
    """Split into words, each carrying its normalized key and its source span.

    The normalized key comes from `normalize_model_key` -- the project's one
    string reducer -- so a vocabulary entry and a word agree on what "the same
    string" means without a second normalization dialect existing.
    """
    words: list[_Word] = []
    for match in _WORD.finditer(text):
        raw = match.group(0)
        key = normalize_model_key(raw)
        if not key:
            # A token made entirely of separators (a bare "-") normalizes to
            # nothing, so it could never equal a key and is dropped rather than
            # left to match a key that is also empty.
            continue
        words.append(_Word(key=key, start=match.start(), end=match.end()))
    return words
