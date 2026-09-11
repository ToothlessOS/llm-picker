"""Small helpers for building the shapes the code under test consumes.

Deliberately not a full factory library: the interesting objects here are plain
dataclasses and dicts, and hiding them behind `factory_boy` would make the tests
harder to read than the code they cover.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from leaderboard.normalization import normalize_model_key


@dataclass
class Row:
    """A parsed LMArena row, as far as `matching` and `persistence` care.

    Mirrors the fields `dedupe_by_model_key` sorts on and the read path reads.
    """

    category: str
    model_name: str
    rank: int | None = None
    organization: str = ""
    license: str = ""
    metric_kind: str = "score"
    metric_value: float | None = None
    metric_lower: float | None = None
    metric_upper: float | None = None
    metric_variance: float | None = None
    sample_size: int | None = None
    session_count: int | None = None
    leaderboard_publish_date: Any = None
    source_metadata: dict = field(default_factory=dict)

    @property
    def model_key(self) -> str:
        return normalize_model_key(self.model_name)


def agent_index(*names: str) -> Any:
    """Build a `MatchIndex` keyed by normalized agent display names.

    Returns the index; payloads are `Row`s so a test can assert on which entry
    won, not merely that some entry did.
    """
    from leaderboard.matching import MatchIndex

    index = MatchIndex()
    for name in names:
        row = Row(category="agent", model_name=name)
        index.add(row.model_key, row)
    return index


def webdev(name: str, rank: int | None) -> Row:
    return Row(category="webdev", model_name=name, rank=rank, metric_kind="rating")
