"""The deterministic cross-source match ladder.

Design constraints, in priority order:

1. **Never guess.** A wrong match is far worse than a missing one: it silently
   attributes one model's benchmark scores to another, and nothing downstream
   can tell. Every rung either produces a single unambiguous candidate or the
   record is reported as unmatched.
2. **No fuzzy matching.** Only exact equality of *normalized* keys is compared.
   Two rungs derive the key they compare against, and both fire only on an exact,
   unique hit: the harness-wrapper fold, which removes a single trailing token
   from a published constant list; and the stated-effort rung, which appends the
   effort level AA's *name* explicitly states to AA's slug (see
   `match_aa_model`). Neither invents a candidate -- they only re-spell one the
   source already stated.
3. **Every decision is auditable.** Each match records the rung that produced
   it, so an entire class of inferred joins can be reviewed and promoted to
   explicit, human-confirmed aliases.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Literal

from .constants import (
    MatchMethod,
    PRIMARY_CATEGORY,
    Source,
    UnmatchedReason,
)
from .normalization import (
    effort_from_name,
    harness_fold,
    has_effort_marker,
    normalize_model_key,
)

MatchStatus = Literal["matched", "unmatched", "ambiguous", "missing_identity"]


@dataclass(frozen=True)
class MatchOutcome:
    """The result of running the ladder for one record."""

    status: MatchStatus
    method: str | None = None
    #: The normalized key that was resolved -- worth recording even on failure,
    #: because it is what a human needs to write an alias against.
    matched_key: str | None = None
    target: Any = None
    candidates: tuple[str, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def is_match(self) -> bool:
        return self.status == "matched"

    @property
    def reason(self) -> str:
        """The `UnmatchedReason` to persist when this is not a match."""
        if self.status == "ambiguous":
            return UnmatchedReason.AMBIGUOUS_MATCH.value
        if self.status == "missing_identity":
            return UnmatchedReason.MISSING_IDENTITY.value
        return UnmatchedReason.NO_LMARENA_MATCH.value


class AliasTable:
    """Human-confirmed identity mappings, consulted before any inference.

    Rows are keyed by the *verbatim upstream spelling* -- the exact string a
    reviewer sees in the unmatched report and copies into the alias. Not
    normalized, so an alias means precisely what it says.
    """

    def __init__(self, rows: Iterable[Any] = ()):
        self._map: dict[tuple[str, str, str], str] = {}
        for row in rows:
            self.add(row.source, row.category, row.raw_name, row.canonical_key)

    def add(self, source: str, category: str, raw_name: str, canonical_key: str) -> None:
        if raw_name:
            self._map[(source, category or "", raw_name)] = canonical_key

    def lookup(self, source: str, category: str, raw_name: str) -> str | None:
        if not raw_name:
            return None
        return self._map.get((source, category or "", raw_name))

    def __len__(self) -> int:
        return len(self._map)


class MatchIndex:
    """A normalized-key index over one side of a join.

    Keys are added in whatever order the caller has; a key with several payloads
    is a genuine ambiguity, not a last-one-wins.
    """

    def __init__(self, *, enable_harness_fold: bool = True):
        self._entries: dict[str, list[Any]] = defaultdict(list)
        self.enable_harness_fold = enable_harness_fold

    # -- construction ------------------------------------------------------ #

    def add(self, key: str, payload: Any) -> None:
        if key:
            self._entries[key].append(payload)

    # -- introspection ----------------------------------------------------- #

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    @property
    def keys(self) -> set[str]:
        return set(self._entries)

    def payloads(self, key: str) -> list[Any]:
        return list(self._entries.get(key, ()))

    # -- rungs ------------------------------------------------------------- #

    def exact(self, key: str) -> MatchOutcome:
        """Rung: exact equality of normalized keys."""
        if not key:
            return MatchOutcome("missing_identity")
        hits = self._entries.get(key)
        if not hits:
            return MatchOutcome("unmatched", matched_key=key)
        if len(hits) == 1:
            return MatchOutcome("matched", matched_key=key, target=hits[0], candidates=(key,))
        # Several upstream rows collapsed onto one key. Refuse to pick.
        return MatchOutcome(
            "ambiguous",
            matched_key=key,
            candidates=(key,),
            detail={"candidate_key": key, "candidate_count": len(hits)},
        )

    def folded(self, key: str) -> MatchOutcome:
        """Rung: strip one evaluation-harness wrapper token, then require a
        unique, unshadowed hit."""
        if not self.enable_harness_fold or not key:
            return MatchOutcome("unmatched", matched_key=key)

        split = harness_fold(key)
        if split is None:
            return MatchOutcome("unmatched", matched_key=key)
        base, stripped = split

        hits = self._entries.get(base)
        if not hits:
            return MatchOutcome("unmatched", matched_key=key)

        shadows = self._siblings(base, exclude=key)
        if shadows:
            # The fold target has more-specific variants present, so we cannot
            # tell which one the harness-wrapped row actually is.
            return MatchOutcome(
                "ambiguous",
                matched_key=base,
                candidates=tuple(shadows),
                detail={
                    "folded_from": key,
                    "stripped": stripped,
                    "shadowed_by": shadows,
                    "note": "fold target has more-specific variants in the index",
                },
            )
        if len(hits) > 1:
            return MatchOutcome(
                "ambiguous",
                matched_key=base,
                candidates=(base,),
                detail={"folded_from": key, "stripped": stripped, "candidate_count": len(hits)},
            )
        return MatchOutcome(
            "matched",
            method=MatchMethod.HARNESS_FOLD.value,
            matched_key=base,
            target=hits[0],
            candidates=(base,),
            detail={"folded_from": key, "stripped": stripped},
        )

    def _siblings(self, base: str, *, exclude: str) -> list[str]:
        """Keys strictly more specific than `base` (i.e. `base-<something>`)."""
        prefix = f"{base}-"
        return sorted(k for k in self._entries if k != base and k != exclude and k.startswith(prefix))


# --------------------------------------------------------------------------- #
# Ladder 1: LMArena category -> LMArena `agent`
# --------------------------------------------------------------------------- #


def match_lmarena_key(
    index: MatchIndex,
    raw_name: str,
    *,
    alias_table: AliasTable | None = None,
    category: str = "",
) -> MatchOutcome:
    """Resolve a `document`/`search`/`webdev` model against the `agent` index.

    `agent` display names and slug-spelled categories both normalize into the
    same space, so the exact rung does the bulk of the work here. The harness
    fold recovers webdev's benchmark wrappers.
    """
    key = normalize_model_key(raw_name)
    if not key:
        return MatchOutcome("missing_identity", detail={"raw_name": raw_name})

    if alias_table is not None:
        alias = alias_table.lookup(Source.LMARENA.value, category, raw_name)
        if alias:
            outcome = index.exact(alias)
            if outcome.is_match:
                return replace(
                    outcome,
                    method=MatchMethod.ALIAS.value,
                    detail={**outcome.detail, "alias_from": raw_name},
                )
            # The alias exists but points at something no longer in the agent
            # set. Surface it: a stale alias is a real, fixable problem.
            return MatchOutcome(
                "unmatched",
                matched_key=alias,
                detail={"alias_from": raw_name, "alias_target_absent": True},
            )

    outcome = index.exact(key)
    if outcome.status in ("matched", "ambiguous"):
        if outcome.is_match:
            return replace(outcome, method=MatchMethod.EXACT_KEY.value)
        return outcome

    return index.folded(key)


# --------------------------------------------------------------------------- #
# Ladder 2: Artificial Analysis -> LMArena `agent`
# --------------------------------------------------------------------------- #


def match_aa_model(
    index: MatchIndex,
    *,
    name: str,
    slug: str,
    alias_table: AliasTable | None = None,
    category: str = PRIMARY_CATEGORY,
) -> MatchOutcome:
    """Resolve an AA record against the `agent` index.

    **Rung order is a correctness property, not a preference.** AA publishes one
    row per reasoning level, but the effort marker's location is inconsistent:
    sometimes it is baked into the slug (``gpt-5-6-luna-low``), sometimes it
    exists only in the name (``gpt-5-5`` -> ``"GPT-5.5 (xhigh)"``). So a bare
    slug can denote a *different* reasoning level than its own record's name:

    ================  ======================  ===========================
    AA slug           AA name                 agent keys
    ================  ======================  ===========================
    ``gpt-5-5``       ``GPT-5.5 (xhigh)``     ``gpt-5-5``, ``gpt-5-5-xhigh``
    ``gpt-6-astra``   ``GPT-6 Astra (max)``   ``gpt-6-astra-max``
    ================  ======================  ===========================

    Keying on the slug first would attach the **xhigh** row to the **base**
    ``GPT 5.5`` -- a plausible-looking, silently wrong answer. The name rung
    resolves it correctly. The slug remains necessary for records whose name
    carries no effort marker at all (``mimo-v2-5-pro`` -> ``"MiMo-V2.5-Pro"``),
    where it is safe, and it is skipped entirely otherwise.

    The final exact rung covers the case the two above cannot reach: AA states an
    effort in *verbose prose* and publishes that variant under the **bare** slug,
    while LMArena keys it with a suffix.

    ================  ==========================================  ==================
    AA slug           AA name                                     agent key
    ================  ==========================================  ==================
    ``claude-opus-5``  ``Claude Opus 5 (Adaptive Reasoning, …``   ``claude-opus-5-max``

    ``has_effort_marker`` cannot see that prose (it ends in ``effort``, not an
    effort word), so the name rung misses and the slug rung -- which is *not*
    skipped, for the same reason -- tries the bare ``claude-opus-5``, which
    LMArena does not have. ``effort_from_name`` reads the stated level and the
    rung appends it.

    This does not weaken the guarantee above, because it never consults the bare
    slug as an answer: it only compares against ``<slug>-<stated effort>``, which
    is strictly *more* specific than the record's slug. It is therefore
    structurally unable to land on a different effort level, which is why it
    needs none of the sibling shadowing check ``MatchIndex.folded`` requires.
    """
    name_key = normalize_model_key(name)
    slug_key = normalize_model_key(slug)
    if not name_key and not slug_key:
        return MatchOutcome("missing_identity", detail={"name": name, "slug": slug})

    if alias_table is not None:
        alias = alias_table.lookup(Source.ARTIFICIAL_ANALYSIS.value, category, name) or (
            alias_table.lookup(Source.ARTIFICIAL_ANALYSIS.value, category, slug)
        )
        if alias:
            outcome = index.exact(alias)
            if outcome.is_match:
                return replace(
                    outcome,
                    method=MatchMethod.ALIAS.value,
                    detail={**outcome.detail, "alias_from": name or slug},
                )
            return MatchOutcome(
                "unmatched",
                matched_key=alias,
                detail={"alias_from": name or slug, "alias_target_absent": True},
            )

    # The slug rung -- and the slug fold -- are gated on the name being silent
    # about reasoning effort. See the docstring above.
    name_states_effort = has_effort_marker(name_key)
    slug_allowed = bool(slug_key) and not name_states_effort

    # Rung: exact AA `name`. Preferred, because it is the field that names the
    # reasoning level.
    if name_key:
        outcome = index.exact(name_key)
        if outcome.is_match:
            return replace(outcome, method=MatchMethod.EXACT_NAME.value)
        if outcome.status == "ambiguous":
            return outcome

    # Rung: exact AA `slug`.
    if slug_allowed:
        outcome = index.exact(slug_key)
        if outcome.is_match:
            return replace(outcome, method=MatchMethod.EXACT_SLUG.value)
        if outcome.status == "ambiguous":
            return outcome

    # Rung: AA's slug with the effort level its name states appended. For the
    # verbose prose dialect, where AA maps the stated level to the bare slug and
    # LMArena keys it with a suffix.
    effort = effort_from_name(name)
    # Guard on token containment, not a suffix test: when the slug already names
    # the effort ("qwen3-8-max-0803", "…-non-reasoning-low-effort") appending it
    # again builds nonsense.
    effort_key = (
        f"{slug_key}-{effort}"
        if effort and slug_key and f"-{effort}-" not in f"-{slug_key}-"
        else None
    )
    if effort_key:
        outcome = index.exact(effort_key)
        if outcome.is_match:
            return replace(
                outcome,
                method=MatchMethod.EXACT_EFFORT_SLUG.value,
                detail={**outcome.detail, "effort": effort, "effort_key": effort_key},
            )
        if outcome.status == "ambiguous":
            return outcome

    # Rung: harness wrapper, on whichever keys were permitted.
    for candidate in filter(None, (name_key, slug_key if slug_allowed else None)):
        outcome = index.folded(candidate)
        if outcome.status in ("matched", "ambiguous"):
            return outcome

    return MatchOutcome(
        "unmatched",
        matched_key=name_key or slug_key,
        detail={
            "name_key": name_key,
            "slug_key": slug_key,
            "name_states_effort": name_states_effort,
            "slug_rung_skipped": bool(slug_key) and name_states_effort,
            # Reported separately, and only when each is true: `effort` when the
            # name stated a level, `effort_key_tried` only when the rung actually
            # consulted a key. A record whose slug already names the effort has
            # the first but not the second, and must not claim an attempt the
            # guard suppressed. Also keeps the sample rows in
            # `docs/unmatched-report.md`, which state no effort, unembellished.
            **({"effort": effort} if effort else {}),
            **({"effort_key_tried": effort_key} if effort_key else {}),
        },
    )


# --------------------------------------------------------------------------- #
# Collision resolution
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Claim:
    """One AA record's claim on one `agent` key."""

    matched_key: str
    method: str
    model: Any
    name: str
    slug: str

    @property
    def slug_is_key(self) -> bool:
        """Does this record's own slug *be* the key it matched?"""
        return normalize_model_key(self.slug) == self.matched_key

    @property
    def rank(self) -> int:
        """Lower is better. Encodes the deterministic tie-break order.

        `exact_effort_slug` outranks `harness_fold` because it re-spells a level
        the source stated rather than inferring one from a wrapper token. It sits
        below the two verbatim rungs: the key it matched exists in neither source
        as written, so a record that matched on a spelling upstream actually uses
        should win.
        """
        if self.method == MatchMethod.ALIAS.value:
            return 0
        if self.slug_is_key:
            return 1
        if self.method == MatchMethod.EXACT_NAME.value:
            return 2
        if self.method == MatchMethod.EXACT_SLUG.value:
            return 3
        if self.method == MatchMethod.EXACT_EFFORT_SLUG.value:
            return 4
        return 5  # harness fold -- inferred


def resolve_collisions(claims: Iterable[Claim]) -> tuple[dict[str, Claim], list[tuple[Claim, Claim]]]:
    """Reduce many claims to one winner per `agent` key.

    AA can publish two rows that normalize to the same agent key -- most often
    the same base model at the same effort level under two slugs. The
    `ModelMatch` uniqueness constraint allows exactly one, so the choice must be
    deterministic and the losers must be reported rather than dropped.

    Returns ``(winners_by_key, [(loser, winner), ...])``.
    """
    grouped: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        grouped[claim.matched_key].append(claim)

    winners: dict[str, Claim] = {}
    losers: list[tuple[Claim, Claim]] = []
    for key, group in grouped.items():
        # Stable: `min` keeps the first of equal elements, and the sort key ends
        # in the slug so ties break lexicographically rather than by input order.
        winner = min(group, key=lambda c: (c.rank, c.slug))
        winners[key] = winner
        losers.extend((claim, winner) for claim in group if claim is not winner)
    return winners, losers


# --------------------------------------------------------------------------- #
# Per-category dedupe
# --------------------------------------------------------------------------- #


def _preference(row: Any) -> tuple:
    """Sort key placing the best row first: lowest rank, then stable on name."""
    return (row.rank is None, row.rank if row.rank is not None else 0, row.model_name)


def dedupe_by_model_key(rows: Iterable[Any]) -> tuple[list[Any], list[tuple[Any, Any]]]:
    """Collapse rows sharing a normalized key down to one canonical row each.

    **Mandatory, not a nicety.** `webdev` publishes 535 rows for 127 real models,
    repeating a model up to nine times with *contradictory* ranks --
    `claude-opus-5-max` appears at ranks 3, 1, 3, 2 and 3. Without this the
    `(category, model_key)` unique constraint would refuse the write and the
    first successful refresh would also be the last.

    The winner is the best-ranked row; ties break on the upstream spelling, so
    the choice is stable across runs and two identical refreshes cannot flip it.
    Runs before any database write, so the constraint can never fire.

    Returns ``(winners, [(loser, winner), ...])`` -- the losers are reported as
    `duplicate_model_name` anomalies rather than dropped silently.
    """
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[row.model_key].append(row)

    winners: list[Any] = []
    losers: list[tuple[Any, Any]] = []
    for group in grouped.values():
        winner = min(group, key=_preference)
        winners.append(winner)
        losers.extend((row, winner) for row in group if row is not winner)

    winners.sort(key=_preference)
    losers.sort(key=lambda pair: _preference(pair[0]))
    return winners, losers
