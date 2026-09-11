"""Seed data for `ModelAlias`, applied by migration 0002.

An alias is the **human-confirmed escape hatch**: a reviewer looks at the
unmatched report, decides that two differently-spelled records really are the
same model, and writes the mapping down. Aliases are consulted before any
inference in the match ladder, so they always win.

An alias is resolved by the match ladder during a refresh, and the join it
produces is stored in `ModelMatch`. So adding one here (or in the Django admin,
which is the intended workflow) makes the model appear on `/overview/` from the
**next refresh** onwards -- the twice-daily scheduled run, or a single
`manage.py refresh_leaderboard --source=aa` when a reviewer wants it applied at
once. No deploy and no code change, but a refresh is required: the served join
always comes from the stored match table, never from inference performed at
request time.

This tuple starts empty on purpose. Seeding it with guesses would defeat the
entire point of refusing to infer reasoning-effort equivalences: every entry
must be a judgement someone actually made. Add entries in this shape once the
unmatched report has been reviewed:

    SeedAlias(
        source=Source.ARTIFICIAL_ANALYSIS,
        category=Category.AGENT,
        raw_name="GPT-5.5 (xhigh)",          # verbatim upstream spelling
        canonical_key="gpt-5-5-xhigh",       # the agent-side normalized key
        note="AA's xhigh row; agent spells the same level '(xHigh)'.",
    )
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedAlias:
    source: str
    category: str
    #: The exact upstream string as it appears in the unmatched report.
    raw_name: str
    #: The normalized key of the record this should be matched to.
    canonical_key: str
    note: str = ""


#: Reviewed, human-confirmed mappings. See the module docstring for the format.
SEED_ALIASES: tuple[SeedAlias, ...] = ()
