"""Enumerations, whitelists and mappings shared across the leaderboard app.

Anything two modules must agree on is defined here exactly once: the category
list, which metric column family a category carries, the ordering/filter
whitelists the API exposes, and the tuning constants for retrieval and matching.
"""

from dataclasses import dataclass

from django.db import models

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


class Source(models.TextChoices):
    """Where a record came from. Shared by SyncRun, UnmatchedRecord and ModelAlias.

    `HACKERNEWS` is a source for *run bookkeeping only*. It is deliberately absent
    from `selectors.freshness_summary()`, which feeds `meta.sources` on every
    endpoint: that block is the per-source freshness of the rows you are reading,
    and Hacker News discussions are not models. Reporting them there would put
    discussion freshness on `/overview/` and widen a contract the frontend types
    as `{lmarena, artificial_analysis}`. HN freshness is served under
    `meta.discussions` instead.

    What the enum *does* buy is the whole run-bookkeeping apparatus, unchanged:
    `run_lock(Source.HACKERNEWS)`, the `SyncRun` partial unique index that stops
    two HN runs overlapping without blocking a model refresh, and
    `source_freshness()`.
    """

    LMARENA = "lmarena", "LMArena"
    ARTIFICIAL_ANALYSIS = "artificial_analysis", "Artificial Analysis"
    HACKERNEWS = "hackernews", "Hacker News"


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
    #: AA handed this row's slug to a *different* `aa_id`, and the row itself has
    #: dropped out of the catalogue. Distinct from `duplicate_model_name`: nothing
    #: is duplicated and nothing was collapsed -- a public slug that used to
    #: address this model now addresses another one, so a bookmark for it lands
    #: somewhere else. Reported once, when the hand-off happens.
    SLUG_REASSIGNED = "slug_reassigned", "Slug reassigned"


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
    #: AA's `slug` with the effort level its NAME states appended. Fires only when
    #: AA names an effort the slug omits, so both sides state the level: AA in
    #: prose ("(Adaptive Reasoning, Max Effort)"), LMArena in the key ("-max").
    #: Unlike the harness fold this cannot land on a different effort level, since
    #: the constructed key is strictly more specific.
    EXACT_EFFORT_SLUG = "exact_effort_slug", "Exact AA slug + stated effort"
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

#: Reasoning-effort markers. Two readers use these, for two different questions:
#: `has_effort_marker` decides whether AA's bare `slug` is safe to consult (it is
#: not, when the name already names an effort level), and `effort_from_name` reads
#: which level the name states so a `<slug>-<effort>` key can be built. `effort`
#: itself is a marker word, not a level, and is deliberately not a member.
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

#: Ordering keys accepted by `/discussions/`.
#:
#: `rank_score` leads because it is the stored "up-votes / number of comments"
#: figure the feature ranks by; the two components are exposed separately so a
#: reader who disagrees with the weighting can reorder without a deploy.
#: `comments_stored` sits beside `num_comments` deliberately: when a thread's tree
#: was truncated, the gap between them is the thing worth seeing.
DISCUSSION_ORDERING: dict[str, str] = {
    "rank_score": "rank_score",
    "points": "points",
    "num_comments": "num_comments",
    "comments_stored": "comments_stored",
    "posted_at": "posted_at",
    "fetched_at": "fetched_at",
    "title": "title",
    "domain": "domain",
}

DEFAULT_OVERVIEW_ORDERING: tuple[str, ...] = ("rank",)
DEFAULT_UNMATCHED_ORDERING: tuple[str, ...] = ("source", "category", "reason", "model_key")
DEFAULT_AA_ORDERING: tuple[str, ...] = ("-intelligence_index",)
DEFAULT_CATEGORY_ORDERING: tuple[str, ...] = ("rank",)
DEFAULT_DISCUSSION_ORDERING: tuple[str, ...] = ("-rank_score",)

#: Pagination bounds. `page_size` above the max is clamped rather than rejected;
#: a non-integer `page_size` is a 400.
DEFAULT_PAGE_SIZE: int = 50
MAX_PAGE_SIZE: int = 200

#: `/discussions/` defaults to the draft's "top 10" rather than the site-wide 50.
#: The full retained bank stays reachable via `?page_size=`.
DEFAULT_DISCUSSION_PAGE_SIZE: int = 10


# --------------------------------------------------------------------------- #
# Hacker News discussions
# --------------------------------------------------------------------------- #


class EntityKind(models.TextChoices):
    """Which of the two filter dropdowns an entity belongs to.

    The draft's phrase "companies / service / provider" names two genuinely
    different things, and conflating them makes both useless: filtering by
    *Anthropic* and filtering by *Cursor* answer different questions.

    There is deliberately no third kind for model variants. Tagging free text
    with an exact model variant is the least reliable match of the three, and a
    thread tagged `claude-opus-5-high` is a much stronger claim than one tagged
    `anthropic` -- so it is out of scope rather than shipped at lower precision.
    """

    VENDOR = "vendor", "Model vendor"
    SERVICE = "service", "Service / product"


class MatchMode(models.TextChoices):
    """How a `ProviderAlias` fires against free text.

    All three modes are **exact**, and none of them does similarity scoring or
    partial credit -- see `hn_matching.py` for why the project's anti-fuzzy rule
    survives this module intact.

    The three exist because a vocabulary has to answer two different questions,
    and one rule cannot answer both:

    * *"Is this word the thing I named?"* -- ``word``. `openai` fires on
      "OpenAI's" and not on "openai-compatible".
    * *"Is this phrase the thing I named?"* -- ``token_run``. `google deepmind`
      fires on both spellings of that phrase, and `gpt-5` still refuses
      "GPT-5-mini".
    * *"Is this a version of the vendor I named?"* -- ``token_prefix``. This is
      the one the other two cannot express, and without it `gpt` does not fire on
      "GPT-5" at all, so a thread titled "GPT-5 released" would not even be
      recognised as an LLM thread.

    ``token_prefix`` is the one the other two cannot express, and without it `gpt`
    does not fire on "GPT-5" at all, so a thread titled "GPT-5 released" would not
    even be recognised as an LLM thread. It matches a leading token run, **or a
    leading run followed by a version number written flush against it** -- so
    `qwen` reaches "Qwen3" as well as "Qwen-3", which matters because that is the
    spelling the project's own normalized model keys use (`qwen3-8-flash-next`).

    It is a **token**-level prefix, never a character-level one -- the alias's
    tokens must be a *leading, complete* token sequence, and any flush remainder
    must begin with a digit. `gpt` therefore fires on "GPT-5" and "GPT-5-mini" but
    not on "gptx", `rag` fires on "rag-pipeline" but not on "rage", and `phi`
    fires on "phi-3" and "phi3" but not on "philosophy" -- which is what makes it
    safe to write a vendor stem down. It is for **vendor and service stems**, not
    for model variants: marking `gpt-5` as a prefix is how "GPT-5-mini" would
    wrongly inherit GPT-5's identity, and that is a rule a reviewer has to keep,
    because the mode is per-alias and visible in the admin for exactly that
    reason.
    """

    #: The alias equals one whole word. `openai` fires on "OpenAI's API".
    WORD = "word", "Whole word"
    #: The alias's tokens equal the *whole* hyphen-joined token run of a word, or
    #: of a run of consecutive words. `gpt-5` fires on "GPT-5" and **not** on
    #: "GPT-5-mini"; `google deepmind` fires on "Google DeepMind".
    TOKEN_RUN = "token_run", "Whole token run"
    #: The alias's tokens are a *leading* token sequence of one word, optionally
    #: followed directly by a version number. `gpt` fires on "GPT-5" and "GPT4";
    #: `qwen` fires on "Qwen3"; `llama` fires on "llama-3-8b". The word must carry
    #: something beyond the alias, so a bare "gpt" is not matched by this mode.
    TOKEN_PREFIX = "token_prefix", "Leading token run"


#: Terms that make a Hacker News story relevant to this project's subject, used
#: by the local relevance filter. Matched as `token_prefix`, so `gpt` reaches
#: "GPT-5" and `claude` reaches "claude-3-opus" -- the list is a list of
#: *subjects*, not an enumeration of versions that would go stale on every
#: release. It is still exact: an alias has to be a leading, complete token
#: sequence, so `rag` does not reach "rage".
#:
#: **Inflection is not covered**, because a token-level prefix cannot reach it:
#: `llms` is one token, not `llm` plus `s`. Both spellings are listed where both
#: are common, and a missing one is fixed by adding a line here rather than by
#: loosening the matcher -- so every term stays one a human chose.
#:
#: This list is code-reviewed configuration rather than a database table, on the
#: `HARNESS_SUFFIXES` precedent: it is evidence-based, small, and changing it is a
#: deploy-worthy decision. The *provider aliases* are different in kind -- those
#: are per-mention judgements a reviewer makes, which is why they live in
#: `ProviderAlias` and are editable in the admin.
HN_RELEVANCE_TERMS: tuple[str, ...] = (
    # Vendors
    "openai",
    "anthropic",
    "google deepmind",
    "deepmind",
    "meta ai",
    "mistral",
    "deepseek",
    "alibaba",
    "moonshot",
    "minimax",
    "zhipu",
    "xai",
    "cohere",
    "hugging face",
    "huggingface",
    "stability ai",
    "nvidia",
    # Models and families
    "llm",
    "llms",
    "gpt",
    "chatgpt",
    "claude",
    "gemini",
    "gemma",
    "llama",
    "qwen",
    "kimi",
    "glm",
    "grok",
    "phi",
    "command r",
    "muse spark",
    # Services and tooling
    "copilot",
    "cursor",
    "windsurf",
    "aider",
    "cline",
    "ollama",
    "vllm",
    "llama.cpp",
    "lm studio",
    "openrouter",
    "bedrock",
    "vertex ai",
    "codex",
    "claude code",
    "gemini cli",
    # Technical vocabulary. Inflections are listed explicitly -- see the note above.
    "transformer",
    "transformers",
    "mixture of experts",
    "quantization",
    "gguf",
    "lora",
    "fine-tuning",
    "finetuning",
    "rag",
    "retrieval augmented generation",
    "embeddings",
    "vector database",
    "vector databases",
    "context window",
    "context windows",
    "reasoning model",
    "reasoning models",
    "chain of thought",
    "prompt engineering",
    "ai agent",
    "ai agents",
    "agentic",
    "mcp",
    "model context protocol",
    "tokenizer",
    "tokenizers",
    "distillation",
    "rlhf",
    "diffusion model",
    "diffusion models",
    "multimodal",
)

#: The priority subset swept over the search API (Stream B). Each term costs one
#: request per sweep, so this is the shortlist of terms distinctive enough that a
#: story mentioning one is worth a query on its own. Must be a subset of
#: `HN_RELEVANCE_TERMS`; asserted by a test so the two cannot drift.
HN_SWEEP_TERMS: tuple[str, ...] = (
    "llm",
    "chatgpt",
    "claude",
    "openai",
    "anthropic",
    "gemini",
    "deepseek",
    "llama",
    "qwen",
    "mistral",
    "grok",
    "cursor",
    "copilot",
    "ollama",
    "vllm",
    "hugging face",
    "openrouter",
    "fine-tuning",
    "ai agent",
    "model context protocol",
)

#: Stems whose *unmatched* occurrences are worth reporting.
#:
#: `claude` deliberately does not match "claude-3-opus" (see `hn_matching.py`), so
#: a stem appearing hundreds of times while tagging nothing is the signal that a
#: human should write an alias. This is the review loop that grows the vocabulary,
#: and it is the reason refusing a prefix mode is affordable rather than merely
#: principled.
HN_ALIAS_WATCHLIST: tuple[str, ...] = (
    "gpt",
    "claude",
    "gemini",
    "llama",
    "qwen",
    "mistral",
    "grok",
    "deepseek",
)


# Defaults for every Hacker News tunable. `settings.py` declares each of these as
# a `LEADERBOARD_HN_*` environment setting with the same literal default, which is
# the precedent `DEFAULT_STALE_AFTER_SECONDS` set. The duplication exists because
# this module must be importable **without settings configured** -- `api/` reads
# these through `hn_config()` on the request path -- and a test asserts the two
# sets agree, so they cannot silently drift.
DEFAULT_HN_ENABLED: bool = True
DEFAULT_HN_BASE_URL: str = "https://hn.algolia.com/api/v1"
DEFAULT_HN_WINDOW_DAYS: int = 14
DEFAULT_HN_WINDOW_SLICE_DAYS: int = 7
DEFAULT_HN_MIN_POINTS: int = 100
DEFAULT_HN_MIN_COMMENTS: int = 20
DEFAULT_HN_SWEEP_MIN_POINTS: int = 30
DEFAULT_HN_SWEEP_MIN_COMMENTS: int = 5
DEFAULT_HN_COMMENT_WEIGHT: float = 1.0
DEFAULT_HN_MAX_TREES_PER_RUN: int = 60
DEFAULT_HN_KEYWORD_QUERY_BUDGET: int = 8
DEFAULT_HN_HITS_PER_PAGE: int = 100
DEFAULT_HN_MAX_PAGE: int = 9
DEFAULT_HN_MAX_COMMENTS: int = 3000
DEFAULT_HN_MAX_STORED_COMMENTS: int = 2500
DEFAULT_HN_MAX_ITEM_BYTES: int = 8_000_000
DEFAULT_HN_TREE_TIMEOUT_SECONDS: float = 45.0
DEFAULT_HN_RUN_BUDGET_SECONDS: int = 600
DEFAULT_HN_MAX_INLINE_RETRY_AFTER_SECONDS: int = 60
DEFAULT_HN_STALE_AFTER_SECONDS: int = 2 * 3600

#: Algolia's hard ceiling: `hitsPerPage * page` cannot exceed 1,000, and past it
#: the API returns a plausible-looking truncated set rather than an error. Kept
#: here so the client, the service and the checks all quote one number.
HN_PAGINATION_CEILING: int = 1000


@dataclass(frozen=True)
class HNConfig:
    """Every Hacker News tunable, resolved once per call.

    A frozen value object rather than a pile of `getattr` calls at each use site,
    so a caller that needs four of them reads one object and cannot accidentally
    mix a configured value with a default.
    """

    enabled: bool
    base_url: str
    window_days: int
    window_slice_days: int
    min_points: int
    min_comments: int
    sweep_min_points: int
    sweep_min_comments: int
    comment_weight: float
    max_trees_per_run: int
    keyword_query_budget: int
    hits_per_page: int
    max_page: int
    max_comments: int
    max_stored_comments: int
    max_item_bytes: int
    tree_timeout_seconds: float
    run_budget_seconds: int
    max_inline_retry_after_seconds: int
    stale_after_seconds: int


def hn_config() -> HNConfig:
    """The effective Hacker News configuration.

    Read lazily through `getattr` so that importing this module never requires
    Django settings to be configured -- the same reason `stale_after_seconds()`
    exists, and what lets `api/` read these without importing the service layer.
    """
    from django.conf import settings

    def read(name: str, default):
        return getattr(settings, name, default)

    return HNConfig(
        enabled=bool(read("LEADERBOARD_HN_ENABLED", DEFAULT_HN_ENABLED)),
        base_url=str(read("LEADERBOARD_HN_BASE_URL", DEFAULT_HN_BASE_URL)),
        window_days=int(read("LEADERBOARD_HN_WINDOW_DAYS", DEFAULT_HN_WINDOW_DAYS)),
        window_slice_days=int(
            read("LEADERBOARD_HN_WINDOW_SLICE_DAYS", DEFAULT_HN_WINDOW_SLICE_DAYS)
        ),
        min_points=int(read("LEADERBOARD_HN_MIN_POINTS", DEFAULT_HN_MIN_POINTS)),
        min_comments=int(read("LEADERBOARD_HN_MIN_COMMENTS", DEFAULT_HN_MIN_COMMENTS)),
        sweep_min_points=int(
            read("LEADERBOARD_HN_SWEEP_MIN_POINTS", DEFAULT_HN_SWEEP_MIN_POINTS)
        ),
        sweep_min_comments=int(
            read("LEADERBOARD_HN_SWEEP_MIN_COMMENTS", DEFAULT_HN_SWEEP_MIN_COMMENTS)
        ),
        comment_weight=float(
            read("LEADERBOARD_HN_COMMENT_WEIGHT", DEFAULT_HN_COMMENT_WEIGHT)
        ),
        max_trees_per_run=int(
            read("LEADERBOARD_HN_MAX_TREES_PER_RUN", DEFAULT_HN_MAX_TREES_PER_RUN)
        ),
        keyword_query_budget=int(
            read("LEADERBOARD_HN_KEYWORD_QUERY_BUDGET", DEFAULT_HN_KEYWORD_QUERY_BUDGET)
        ),
        hits_per_page=int(read("LEADERBOARD_HN_HITS_PER_PAGE", DEFAULT_HN_HITS_PER_PAGE)),
        max_page=int(read("LEADERBOARD_HN_MAX_PAGE", DEFAULT_HN_MAX_PAGE)),
        max_comments=int(read("LEADERBOARD_HN_MAX_COMMENTS", DEFAULT_HN_MAX_COMMENTS)),
        max_stored_comments=int(
            read("LEADERBOARD_HN_MAX_STORED_COMMENTS", DEFAULT_HN_MAX_STORED_COMMENTS)
        ),
        max_item_bytes=int(read("LEADERBOARD_HN_MAX_ITEM_BYTES", DEFAULT_HN_MAX_ITEM_BYTES)),
        tree_timeout_seconds=float(
            read("LEADERBOARD_HN_TREE_TIMEOUT_SECONDS", DEFAULT_HN_TREE_TIMEOUT_SECONDS)
        ),
        run_budget_seconds=int(
            read("LEADERBOARD_HN_RUN_BUDGET_SECONDS", DEFAULT_HN_RUN_BUDGET_SECONDS)
        ),
        max_inline_retry_after_seconds=int(
            read(
                "LEADERBOARD_HN_MAX_INLINE_RETRY_AFTER_SECONDS",
                DEFAULT_HN_MAX_INLINE_RETRY_AFTER_SECONDS,
            )
        ),
        stale_after_seconds=int(
            read("LEADERBOARD_HN_STALE_AFTER_SECONDS", DEFAULT_HN_STALE_AFTER_SECONDS)
        ),
    )
