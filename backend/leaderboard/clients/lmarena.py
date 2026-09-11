"""LMArena leaderboard dataset client.

    load_dataset("lmarena-ai/leaderboard-dataset", "<field>", split="latest")

Only the `latest` split is ever requested -- there is deliberately no code path
that can ask for `full`, because this project records current leaderboard state
and has no snapshot tables to put history in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from ..validation import ValidationError, check_columns
from .exceptions import SchemaError, SourceError

DEFAULT_DATASET_ID = "lmarena-ai/leaderboard-dataset"
DEFAULT_SPLIT = "latest"


@dataclass(frozen=True)
class LoadedSplit:
    """One category's `latest` split, already materialized."""

    columns: list[str]
    rows: list[dict[str, Any]]
    revision: str = ""


def _default_loader(dataset_id: str, field: str) -> LoadedSplit:
    """Load a split through the Hugging Face `datasets` library.

    `datasets` is imported *inside* this function, never at module scope: the
    DRF process must not pay its import cost, and must not be one stray call
    away from performing a dataset download while serving a request.
    """
    from datasets import load_dataset

    dataset = load_dataset(dataset_id, field, split=DEFAULT_SPLIT)
    columns = list(getattr(dataset, "column_names", None) or [])
    rows = [dict(row) for row in dataset]

    revision = ""
    info = getattr(dataset, "info", None)
    version = getattr(info, "version", None)
    if version is not None:
        revision = str(version)

    return LoadedSplit(columns=columns, rows=rows, revision=revision)


class LMArenaClient:
    def __init__(
        self,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        loader: Callable[[str, str], LoadedSplit] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 2,
        backoff: float = 2.0,
    ):
        self._dataset_id = dataset_id
        self._loader = loader if loader is not None else _default_loader
        self._sleep = sleep
        self._max_attempts = max(1, max_attempts)
        self._backoff = backoff

    @property
    def dataset_id(self) -> str:
        return self._dataset_id

    def fetch_category(self, category: str) -> LoadedSplit:
        """Load one category, validating its schema before anything is written.

        A schema mismatch fails *this category*; the caller decides whether that
        is fatal (it is for `agent`, which anchors every intersection).
        """
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                split = self._loader(self._dataset_id, category)
            except Exception as exc:  # noqa: BLE001
                # Intentionally broad. `datasets` surfaces a wide and unstable
                # set of exception types for network, Hub and Arrow failures, and
                # narrowing the catch would let a transient one escape unretried.
                # The budget is a single retry, so a genuine bug costs one extra
                # call, not a loop.
                last_error = exc
                if attempt < self._max_attempts:
                    self._sleep(self._backoff)
                continue

            try:
                check_columns(category, split.columns)
            except ValidationError as exc:
                # A schema change is not transient -- never retried.
                raise SchemaError(
                    f"LMArena split {category!r} failed schema validation: {exc}",
                    detail={"category": category, "field": exc.field},
                ) from exc

            return split

        raise SourceError(
            f"LMArena split {category!r} failed to load after {self._max_attempts} attempts: "
            f"{type(last_error).__name__}: {last_error}",
            detail={"category": category, "exception": type(last_error).__name__},
        )
