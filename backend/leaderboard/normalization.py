"""Deterministic model-name normalization.

This module exists because the two LMArena naming conventions **do not join on
their own**, and neither does LMArena against Artificial Analysis:

* LMArena `agent` uses display names -- ``"Claude Opus 5 (High)"``.
* LMArena `document` / `search` / `webdev` use slugs -- ``claude-opus-5-high``.
* Artificial Analysis uses a ``name`` that may or may not name a reasoning level
  (``"GPT-5.5 (xhigh)"``) alongside a ``slug`` that may name a *different* one
  (``gpt-5-5``).

Exact string comparison across any of those pairs yields a **zero** intersection.
Everything here is a pure function of its input: no fuzzy scoring, no similarity
thresholds, no external state.

Two of the readers below look for a reasoning effort and must not be confused:
`has_effort_marker` answers "is AA's bare slug unsafe to consult?" and is blind to
AA's verbose prose on purpose; `effort_from_name` answers "which level does the
name state?" and is the one that reads the prose.
"""

from __future__ import annotations

import re
import unicodedata

from .constants import EFFORT_TOKENS, HARNESS_SUFFIXES

#: Every run of characters that is not a lowercase ASCII letter or digit becomes
#: a single hyphen. Applied *after* case folding, so this is the whole alphabet.
_NON_ALNUM_RUN = re.compile(r"[^a-z0-9]+")


def normalize_model_key(value: object) -> str:
    """Reduce a model name or slug to its canonical join key.

    NFKC -> strip combining marks -> casefold -> non-alphanumeric runs to ``-``
    -> trim hyphens.

    Parenthetical variant suffixes are **preserved**, which is the entire point:
    ``"Claude Opus 5 (High)"`` -> ``claude-opus-5-high`` and
    ``claude-opus-5-high`` -> ``claude-opus-5-high`` are then equal, while
    ``claude-opus-5`` stays distinct from ``claude-opus-5-high``.

    Reasoning effort is part of a model's identity here, not decoration. Folding
    it away produced exactly one match on real data and that match was wrong.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    # NFKD then dropping combining marks so that an accented spelling and a plain
    # one land on the same key.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _NON_ALNUM_RUN.sub("-", text.casefold())
    return text.strip("-")


def has_effort_marker(model_key: str) -> bool:
    """Does this normalized key end in a reasoning-effort marker?

    Used for exactly one decision: whether Artificial Analysis' bare ``slug`` is
    safe to consult as a fallback. It is not, when the ``name`` already names an
    effort level -- see ``matching.match_aa_model``.

    Checks the trailing one and two tokens, because ``non-reasoning`` normalizes
    to two hyphen-joined words.

    Its blindness to AA's verbose prose (``"…(Adaptive Reasoning, Max Effort)"``
    ends in ``effort``, not an effort word) is deliberate and permanent -- it is
    what keeps the bare slug rung closed for those records. The prose is read
    instead by `effort_from_name`, which serves a different purpose. Do not widen
    this to cover the verbose form, and do not merge the two.
    """
    if not model_key:
        return False
    tokens = model_key.split("-")
    if tokens[-1] in EFFORT_TOKENS:
        return True
    if len(tokens) >= 2 and "-".join(tokens[-2:]) in EFFORT_TOKENS:
        return True
    return False


def effort_from_name(name: object) -> str | None:
    """The reasoning-effort token AA *explicitly states* in `name`, or ``None``.

    Deliberately not `has_effort_marker`, and the two must not be merged: that
    one gates whether AA's bare ``slug`` is safe to consult, this one reads what
    the name says so that a key can be *constructed* from it. Its silence and its
    speech both have to be deliberate.

    Reads both AA dialects:

    * terse parenthetical -- ``"GPT-5.5 (xhigh)"`` -> ``xhigh``
    * verbose prose -- ``"Claude Opus 5 (Adaptive Reasoning, Max Effort)"`` -> ``max``

    The word ``Effort`` is **required** in the prose form. That is what makes the
    statement explicit rather than inferred, and it is the line between this
    reader and the effort *fold* this project rejected. ``"(Adaptive Reasoning,
    Max)"`` therefore returns ``None`` -- only what is stated counts.

    The contract is "what the name states", not "what the model's effort is": a
    product name containing an effort word (``"Qwen3.8 Max"``) returns ``max``.
    Callers use the result only to build a candidate key, where an over-eager
    answer is suppressed by the caller's guard; this must not be used to make a
    judgement about a model's effort.
    """
    key = normalize_model_key(name)
    if not key:
        return None
    tokens = key.split("-")
    # Terse parenthetical, mirroring `has_effort_marker` including its two-token
    # case, so the two functions cannot disagree about which token they saw.
    if tokens[-1] in EFFORT_TOKENS:
        return tokens[-1]
    if len(tokens) >= 2 and "-".join(tokens[-2:]) in EFFORT_TOKENS:
        return "-".join(tokens[-2:])
    # Verbose prose: "<level> Effort", anywhere in the name.
    for index in range(len(tokens) - 1):
        if tokens[index + 1] == "effort" and tokens[index] in EFFORT_TOKENS:
            return tokens[index]
    return None


def harness_fold(model_key: str) -> tuple[str, str] | None:
    """Strip one trailing evaluation-harness wrapper token.

    Returns ``(base_key, stripped_suffix)``, or ``None`` when the key is not
    wrapped. The suffix list is deliberately tiny and evidence-based: a harness
    suffix *wraps* a model for benchmarking rather than naming a distinct model,
    so removing it recovers the underlying identity. Effort tokens are not in
    that list and never will be.
    """
    if not model_key:
        return None
    # Longest first, so a hypothetical multi-token suffix wins over a shorter one
    # it contains.
    for suffix in sorted(HARNESS_SUFFIXES, key=len, reverse=True):
        tail = f"-{suffix}"
        if model_key.endswith(tail) and len(model_key) > len(tail):
            return model_key[: -len(tail)], suffix
    return None
