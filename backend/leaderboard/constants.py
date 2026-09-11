"""Enumerations, whitelists and mappings shared across the leaderboard app.

Anything two modules must agree on is defined here exactly once: the category
list, which metric column family a category carries, the ordering/filter
whitelists the API exposes, and the tuning constants for retrieval and matching.
"""

from django.db import models

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


class Source(models.TextChoices):
    """Where a record came from. Shared by SyncRun, UnmatchedRecord and ModelAlias."""

    LMARENA = "lmarena", "LMArena"
    ARTIFICIAL_ANALYSIS = "artificial_analysis", "Artificial Analysis"


# --------------------------------------------------------------------------- #
# LMArena categories
# --------------------------------------------------------------------------- #


class Category(models.TextChoices):
    """The four LMArena leaderboard fields this project ingests.

    These are Hugging Face *config* names, not the spec's prose names -- they are
    what `load_dataset("lmarena-ai/leaderboard-dataset", "<field>", split="latest")`
    expects.
    """

    AGENT = "agent", "Agent"
    DOCUMENT = "document", "Document"
    SEARCH = "search", "Search"
    WEBDEV = "webdev", "WebDev"


#: The four categories as plain strings, in the order the frontend should show them.
CATEGORIES: tuple[str, ...] = tuple(category.value for category in Category)

#: `agent` is the primary model set. The other three are intersected against it.
PRIMARY_CATEGORY: str = Category.AGENT.value

#: Categories that are intersected with `agent` before being retained.
INTERSECTED_CATEGORIES: tuple[str, ...] = tuple(
    category for category in CATEGORIES if category != PRIMARY_CATEGORY
)


class MetricKind(models.TextChoices):
    """Which upstream column family a category's numbers came from.

    `agent` publishes an Elo-style `score`; `document`/`search`/`webdev` publish a
    Bradley-Terry `rating`. These are NOT on a comparable scale, so the kind
    travels with the value all the way into the API response and the frontend
    must not plot the two on one axis.
    """

    SCORE = "score", "Score"
    RATING = "rating", "Rating"


CATEGORY_METRIC_KIND: dict[str, str] = {
    Category.AGENT.value: MetricKind.SCORE.value,
    Category.DOCUMENT.value: MetricKind.RATING.value,
    Category.SEARCH.value: MetricKind.RATING.value,
    Category.WEBDEV.value: MetricKind.RATING.value,
}


# --------------------------------------------------------------------------- #
# Ingestion status
# --------------------------------------------------------------------------- #


class SyncStatus(models.TextChoices):
    """Terminal state of one ingestion run for one source.

    `PARTIAL` means some -- but not all -- LMArena fields landed. It is a success
    for freshness purposes (the data that arrived was written and is good), but
    it is surfaced separately so a missing category is never mistaken for a
    category that is genuinely empty upstream.
    """

    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


#: Statuses that count as "we have good data as of this run".
SUCCESSFUL_STATUSES: tuple[str, ...] = (SyncStatus.SUCCESS.value, SyncStatus.PARTIAL.value)


class UnmatchedReason(models.TextChoices):
    """Why a record did not make it into the joined, complete data set.

    Every one of these is reviewable via `manage.py report_unmatched` and
    `GET /api/v1/leaderboard/unmatched/`. Nothing is dropped silently.
    """

    #: An AA model that matched no LMArena `agent` entry.
    NO_LMARENA_MATCH = "no_lmarena_match", "No LMArena match"
    #: The mirror image: an LMArena `agent` model that no AA record resolved to.
    #: This is the population the completeness rule removes from `/overview/`,
    #: so it must be the *best* reported one -- it is the only reason a
    #: perfectly good agent row is missing from the joined surface, and the
    #: review question ("does AA lack it, or does our normalizer need an
    #: alias?") is answerable only by name.
    NO_AA_MATCH = "no_aa_match", "No Artificial Analysis match"
    #: A document/search/webdev model absent from the `agent` split.
    NOT_IN_AGENT_SET = "not_in_agent_set", "Not in agent set"
    #: More than one candidate matched, so we refused to guess.
    AMBIGUOUS_MATCH = "ambiguous_match", "Ambiguous match"
    #: Several upstream rows collapsed onto one normalized key (e.g. webdev's
    #: 535 rows / 127 models). The winner is kept; the losers are listed here.
    DUPLICATE_MODEL_NAME = "duplicate_model_name", "Duplicate model name"
    #: A payload that failed schema validation.
    VALIDATION_FAILED = "validation_failed", "Validation failed"
    #: No usable identity field at all (missing/blank name).
    MISSING_IDENTITY = "missing_identity", "Missing identity"


class MatchMethod(models.TextChoices):
    """How a match was established. Recorded on every ModelMatch so inferred
    joins are auditable as a class and can be promoted to explicit aliases."""

    #: A human wrote a ModelAlias row. Always wins.
    ALIAS = "alias", "Alias override"
    #: Exact equality of normalized keys (LMArena category -> agent).
    EXACT_KEY = "exact_key", "Exact normalized key"
    #: Exact equality against AA's `name` (the preferred AA rung).
    EXACT_NAME = "exact_name", "Exact AA name"
    #: Exact equality against AA's `slug`. Only consulted when the name carries
    #: no reasoning-effort marker -- see `matching.py` for why the order matters.
    EXACT_SLUG = "exact_slug", "Exact AA slug"
    #: Recovered by stripping one evaluation-harness wrapper token.
    HARNESS_FOLD = "harness_fold", "Harness-wrapper fold"


# --------------------------------------------------------------------------- #
# Matching configuration
# --------------------------------------------------------------------------- #

#: Evaluation-harness wrappers: trailing tokens that *wrap* a model for
#: benchmarking rather than name a distinct model. Deliberately tiny and
#: evidence-based -- `codex-harness` is the only one observed in the real data.
#:
#: Reasoning-effort tokens (`high`, `xhigh`, `max`, `low`, `minimal`, ...) are
#: deliberately NOT here. Effort is part of a model's identity, not a wrapper
#: around it: folding it produced exactly one match on real data and that match
#: was wrong.
HARNESS_SUFFIXES: frozenset[str] = frozenset({"codex-harness"})

#: Reasoning-effort markers, used for one thing only: deciding whether AA's bare
#: `slug` is safe to consult as a fallback (it is not, when the name already
#: names an effort level).
EFFORT_TOKENS: frozenset[str] = frozenset(
    {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "thinking",
        "non-reasoning",
        "nonreasoning",
    }
)


# --------------------------------------------------------------------------- #
# AA retrieval configuration
# --------------------------------------------------------------------------- #

#: Hard ceiling on pages fetched in one AA run. AA reports `has_more` itself, but
#: an upstream bug that reports it forever would otherwise burn the whole
#: 100-request/24h quota in a tight loop. Steady state is 4.
AA_MAX_PAGES: int = 8

#: Rate-limit windows longer than this are not worth sleeping through inside a
#: worker: fail the run honestly and let the next scheduled refresh pick it up.
AA_MAX_INLINE_RETRY_AFTER_SECONDS: int = 60


# --------------------------------------------------------------------------- #
# Freshness / staleness
# --------------------------------------------------------------------------- #

#: How long a source's data may go unrefreshed before the API flags it stale.
#: The schedule runs twice daily, so this tolerates one missed run.
DEFAULT_STALE_AFTER_SECONDS: int = 60 * 60 * 14  # 14 hours


def stale_after_seconds() -> int:
    """The configured staleness threshold.

    Lives here rather than in either consumer because both the refresh service
    and the read-only API need the same number, and the API must be able to ask
    for it *without* importing the service layer -- the service layer imports
    the HTTP clients, and no request may be one import away from one.

    Read lazily via `getattr` so that importing this module never requires
    Django settings to be configured.
    """
    from django.conf import settings

    return int(getattr(settings, "LEADERBOARD_STALE_AFTER_SECONDS", DEFAULT_STALE_AFTER_SECONDS))


# --------------------------------------------------------------------------- #
# API whitelists
# --------------------------------------------------------------------------- #

#: Numeric LLMModel columns the API may expose, filter and order by. The key is
#: the name used in query parameters and in API responses (prefixed `aa_` when
#: nested); the value is the real model field.
AA_NUMERIC_FIELDS: dict[str, str] = {
    "intelligence_index": "intelligence_index",
    "coding_index": "coding_index",
    "agentic_index": "agentic_index",
    "intelligence_index_total_cost": "intelligence_index_total_cost",
    "cost_per_task": "cost_per_task",
    "price_1m_input_tokens": "price_1m_input_tokens",
    "price_1m_output_tokens": "price_1m_output_tokens",
    "price_1m_cache_hit_tokens": "price_1m_cache_hit_tokens",
    "price_1m_cache_write_tokens": "price_1m_cache_write_tokens",
    "median_output_tokens_per_second": "median_output_tokens_per_second",
    "median_time_to_first_token_seconds": "median_time_to_first_token_seconds",
    "median_time_to_first_answer_token_seconds": "median_time_to_first_answer_token_seconds",
    "median_end_to_end_response_time_seconds": "median_end_to_end_response_time_seconds",
}

#: Ordering keys accepted by `/artificial-analysis/`.
AA_ORDERING: dict[str, str] = {
    "name": "name",
    "slug": "slug",
    "release_date": "release_date",
    "creator": "creator__name",
    "last_synced_at": "last_synced_at",
    **{key: value for key, value in AA_NUMERIC_FIELDS.items()},
}

#: Ordering keys accepted by `/overview/`. Values are ORM lookups from the
#: LMArenaEntry base queryset, which is why the joined fields reach through
#: `aa_match__model`.
OVERVIEW_ORDERING: dict[str, str] = {
    "rank": "rank",
    "model_name": "model_name",
    "organization": "organization",
    "metric_value": "metric_value",
    "sample_size": "sample_size",
    "session_count": "session_count",
    "leaderboard_publish_date": "leaderboard_publish_date",
    **{
        f"aa_{key}": f"aa_match__model__{value}"
        for key, value in AA_NUMERIC_FIELDS.items()
    },
}

#: Ordering keys accepted by `/categories/{category}/`.
CATEGORY_ORDERING: dict[str, str] = {
    "rank": "rank",
    "model_name": "model_name",
    "organization": "organization",
    "metric_value": "metric_value",
    "sample_size": "sample_size",
    "session_count": "session_count",
    "leaderboard_publish_date": "leaderboard_publish_date",
}

#: Ordering keys accepted by `/unmatched/`.
UNMATCHED_ORDERING: dict[str, str] = {
    "source": "source",
    "category": "category",
    "reason": "reason",
    "model_key": "model_key",
    "model_name": "model_name",
    "organization": "organization",
    "occurrences": "occurrences",
    "first_seen_at": "first_seen_at",
    "last_seen_at": "last_seen_at",
}

DEFAULT_OVERVIEW_ORDERING: tuple[str, ...] = ("rank",)
DEFAULT_UNMATCHED_ORDERING: tuple[str, ...] = ("source", "category", "reason", "model_key")
DEFAULT_AA_ORDERING: tuple[str, ...] = ("-intelligence_index",)
DEFAULT_CATEGORY_ORDERING: tuple[str, ...] = ("rank",)

#: Pagination bounds. `page_size` above the max is clamped rather than rejected;
#: a non-integer `page_size` is a 400.
DEFAULT_PAGE_SIZE: int = 50
MAX_PAGE_SIZE: int = 200
