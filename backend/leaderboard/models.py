"""Leaderboard data model.

Latest-only by design: one current row per entity, upserted on every refresh.
There are no snapshot or time-series tables -- the project records *current*
leaderboard state and how fresh it is, not history.

Two typing rules run through the whole schema, both taken straight from the
source contracts:

* **Money and cost are `DecimalField`.** Summing floats across a cost-per-task
  chart drifts; decimals do not.
* **Indices, latency and throughput are `FloatField`.** They are already
  approximate measurements and carry no currency semantics.

Upstream `null` maps to database `NULL` and **never to `0`**: the AA OpenAPI
spec is explicit that a null means "not measured", and a zero would draw a real
data point at the origin of every chart.
"""

from django.db import models
from django.db.models import Q

from .constants import (
    Category,
    MatchMethod,
    MetricKind,
    Source,
    SyncStatus,
    UnmatchedReason,
)

#: Costs and prices. 6 decimal places comfortably covers AA's 4-dp cost-per-task
#: rounding and sub-cent cache pricing; 6 integer digits covers the most
#: expensive frontier model on the board.
MONEY_FIELD_KWARGS = {
    "max_digits": 12,
    "decimal_places": 6,
    "null": True,
    "blank": True,
}


class ModelCreator(models.Model):
    """An AA `model_creator`. Free-tier responses expose only `id` and `name`."""

    aa_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    first_seen_at = models.DateTimeField()
    last_synced_at = models.DateTimeField()

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class LLMModel(models.Model):
    """Current Artificial Analysis state for one model variant.

    AA publishes **one row per reasoning level**, so a "model" here is really a
    (base model, effort) pair -- `gpt-5-5` with name `GPT-5.5 (xhigh)` and
    `gpt-5-6-luna-low` are both rows in this table.
    """

    #: AA's UUID. This -- not `slug` -- is the upsert key, so that a slug rename
    #: updates the existing row instead of creating a duplicate.
    aa_id = models.CharField(max_length=64, unique=True)
    slug = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    creator = models.ForeignKey(
        ModelCreator,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="models",
    )
    release_date = models.DateField(null=True, blank=True)

    intelligence_index_version = models.FloatField(null=True, blank=True)
    intelligence_index = models.FloatField(null=True, blank=True)
    coding_index = models.FloatField(null=True, blank=True)
    agentic_index = models.FloatField(null=True, blank=True)

    intelligence_index_total_cost = models.DecimalField(**MONEY_FIELD_KWARGS)
    cost_per_task = models.DecimalField(**MONEY_FIELD_KWARGS)

    price_1m_input_tokens = models.DecimalField(**MONEY_FIELD_KWARGS)
    price_1m_output_tokens = models.DecimalField(**MONEY_FIELD_KWARGS)
    price_1m_cache_hit_tokens = models.DecimalField(**MONEY_FIELD_KWARGS)
    price_1m_cache_write_tokens = models.DecimalField(**MONEY_FIELD_KWARGS)

    median_output_tokens_per_second = models.FloatField(null=True, blank=True)
    median_time_to_first_token_seconds = models.FloatField(null=True, blank=True)
    median_time_to_first_answer_token_seconds = models.FloatField(null=True, blank=True)
    median_end_to_end_response_time_seconds = models.FloatField(null=True, blank=True)

    #: In the retained LMArena `agent` subset. AA rows outside this set are still
    #: stored (they cost nothing extra -- the page was already fetched) but are
    #: flagged rather than served by default.
    is_retained = models.BooleanField(default=False)
    #: False once a model disappears from a *fully successful* refresh. Never deleted.
    is_active = models.BooleanField(default=True)

    #: The upstream record verbatim, kept for troubleshooting schema drift.
    #: Never exposed through the API.
    raw_payload = models.JSONField(default=dict, blank=True)

    first_seen_at = models.DateTimeField()
    last_synced_at = models.DateTimeField()

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_retained", "is_active"]),
            models.Index(fields=["intelligence_index"]),
            models.Index(fields=["cost_per_task"]),
            models.Index(fields=["creator", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class LMArenaEntry(models.Model):
    """Current LMArena state for one model in one category.

    The four categories publish different column families, normalized here into
    one shape (`metric_*` / `sample_size` / `session_count`) with `metric_kind`
    recording which family it came from.
    """

    category = models.CharField(max_length=32, choices=Category.choices)
    #: Normalized join key. `agent` display names and the other categories' slugs
    #: both reduce to this, which is what makes the cross-category join possible.
    model_key = models.CharField(max_length=255)
    #: The upstream spelling, verbatim -- shown to users, and the input a human
    #: writes a ModelAlias against.
    model_name = models.CharField(max_length=255)
    organization = models.CharField(max_length=255, blank=True, default="")
    license = models.CharField(max_length=255, blank=True, default="")
    rank = models.IntegerField(null=True, blank=True)

    metric_kind = models.CharField(max_length=16, choices=MetricKind.choices)
    metric_value = models.FloatField(null=True, blank=True)
    metric_lower = models.FloatField(null=True, blank=True)
    metric_upper = models.FloatField(null=True, blank=True)
    #: Only the rating categories publish this; null for `agent`.
    metric_variance = models.FloatField(null=True, blank=True)
    #: `observation_count` for agent, `vote_count` for the rest.
    sample_size = models.IntegerField(null=True, blank=True)
    #: `agent` only.
    session_count = models.IntegerField(null=True, blank=True)

    leaderboard_publish_date = models.DateField(null=True, blank=True)

    #: Present in the latest `agent` split. This is the flag the read-time
    #: intersection filter uses; it is *not* a deletion.
    #: Invariant: `in_agent_set == (agent_key is not None)`.
    in_agent_set = models.BooleanField(default=False)

    #: The `agent`-side key this entry belongs to. Almost always equal to
    #: `model_key`; it differs exactly when the association came from the
    #: harness-wrapper fold (`gpt-5.6-sol-xhigh (codex-harness)` ->
    #: `gpt-5-6-sol-xhigh`), which is precisely the case worth being able to
    #: see and audit. Joining category blocks on this rather than on
    #: `model_key` is what makes those folded rows findable from the overview.
    #: Null when the entry is not in the agent set.
    agent_key = models.CharField(max_length=255, null=True, blank=True)

    is_active = models.BooleanField(default=True)

    #: Unused upstream columns, retained for provenance. Never exposed via the API.
    source_metadata = models.JSONField(default=dict, blank=True)

    first_seen_at = models.DateTimeField()
    last_synced_at = models.DateTimeField()

    class Meta:
        ordering = ["category", "rank"]
        verbose_name_plural = "LMArena entries"
        constraints = [
            # Guarantees the refresh is idempotent. Per-category dedupe upstream
            # of this constraint is what keeps it from ever firing.
            models.UniqueConstraint(
                fields=["category", "model_key"],
                name="uniq_lmarena_entry_category_model_key",
            ),
        ]
        indexes = [
            models.Index(fields=["category", "in_agent_set", "is_active"]),
            models.Index(fields=["category", "rank"]),
            models.Index(fields=["model_key"]),
            models.Index(fields=["organization"]),
        ]

    def __str__(self) -> str:
        return f"{self.category}/{self.model_name}"


class ModelMatch(models.Model):
    """The AA -> LMArena `agent` link, with its provenance.

    A dedicated table rather than a nullable FK on `LLMModel`, because the
    match method and confidence are exactly what the unmatched-review workflow
    has to justify: "why is this model here, and how sure are we?"
    """

    lmarena_entry = models.OneToOneField(
        LMArenaEntry,
        on_delete=models.CASCADE,
        related_name="aa_match",
    )
    model = models.OneToOneField(
        LLMModel,
        on_delete=models.CASCADE,
        related_name="lmarena_match",
    )
    match_method = models.CharField(max_length=32, choices=MatchMethod.choices)
    #: 1.0 for matches whose key the sources themselves state -- the exact rungs,
    #: aliases, and `exact_effort_slug` (the key is constructed, but every part of
    #: it is stated: AA names the level, LMArena's suffix names it too, and the
    #: result cannot land on a different level). Below 1.0 for `harness_fold`,
    #: which strips a wrapper token and so genuinely infers.
    confidence = models.FloatField(default=1.0)
    #: True when a human wrote the alias that produced this match.
    is_manual = models.BooleanField(default=False)
    matched_key = models.CharField(max_length=255)
    last_matched_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["match_method"]),
        ]

    def __str__(self) -> str:
        return f"{self.lmarena_entry.model_name} <-> {self.model.name} ({self.match_method})"


class UnmatchedRecord(models.Model):
    """A record that did not make it into the served, complete data set.

    Current-state semantics: upserted per (source, category, reason, model_key)
    rather than appended per run, so the table stays bounded and re-running a
    refresh is idempotent. `occurrences` counts how many times we have seen it.
    """

    source = models.CharField(max_length=32, choices=Source.choices)
    #: Blank for source-level reasons that are not category-specific.
    category = models.CharField(max_length=32, blank=True, default="")
    reason = models.CharField(max_length=32, choices=UnmatchedReason.choices)

    model_key = models.CharField(max_length=255)
    model_name = models.CharField(max_length=255, blank=True, default="")
    organization = models.CharField(max_length=255, blank=True, default="")

    occurrences = models.PositiveIntegerField(default=1)
    #: False once the record stops appearing upstream. Kept, not deleted.
    is_current = models.BooleanField(default=True)

    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()

    #: Reason-specific context: candidate lists for ambiguity, both ranks for a
    #: duplicate, the stripped token for a fold, and so on.
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["source", "category", "reason", "model_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "category", "reason", "model_key"],
                name="uniq_unmatched_record_identity",
            ),
        ]
        indexes = [
            models.Index(fields=["reason", "is_current"]),
            models.Index(fields=["source", "category"]),
        ]

    def __str__(self) -> str:
        return f"{self.reason}: {self.model_name or self.model_key}"


class SyncRun(models.Model):
    """One ingestion attempt for one source: status, counters and freshness.

    Freshness is *derived* from these rows at read time and never denormalized
    onto the data tables -- staleness depends on "now", so a stored flag is
    wrong the moment it is written.
    """

    source = models.CharField(max_length=32, choices=Source.choices)
    status = models.CharField(max_length=16, choices=SyncStatus.choices)
    triggered_by = models.CharField(max_length=64, blank=True, default="")
    dry_run = models.BooleanField(default=False)
    celery_task_id = models.CharField(max_length=64, blank=True, default="")

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)

    # -- Artificial Analysis specifics ------------------------------------- #
    tier = models.CharField(max_length=32, blank=True, default="")
    intelligence_index_version = models.FloatField(null=True, blank=True)
    page_size = models.IntegerField(null=True, blank=True)
    total_pages = models.IntegerField(null=True, blank=True)
    pages_fetched = models.IntegerField(null=True, blank=True)
    rate_limit_limit = models.IntegerField(null=True, blank=True)
    rate_limit_remaining = models.IntegerField(null=True, blank=True)
    rate_limit_reset_at = models.DateTimeField(null=True, blank=True)

    # -- source-neutral counters ------------------------------------------- #
    records_seen = models.IntegerField(default=0)
    records_created = models.IntegerField(default=0)
    records_updated = models.IntegerField(default=0)
    records_unchanged = models.IntegerField(default=0)
    records_deactivated = models.IntegerField(default=0)
    records_failed = models.IntegerField(default=0)
    records_deduplicated = models.IntegerField(default=0)
    anomalies_recorded = models.IntegerField(default=0)

    # -- LMArena specifics -------------------------------------------------- #
    #: Categories that loaded successfully this run, e.g. ["agent", "webdev"].
    fields_succeeded = models.JSONField(default=list, blank=True)
    #: category -> error string for the ones that did not.
    fields_failed = models.JSONField(default=dict, blank=True)
    dataset_revision = models.CharField(max_length=128, blank=True, default="")

    #: Derived facts about what this run saw, computed in memory before any
    #: write. This exists so a **dry run can report its coverage**: a rollback
    #: erases the rows, so anything re-derived from the database afterwards would
    #: describe the previous state and silently read as a forecast it is not.
    summary = models.JSONField(default=dict, blank=True)

    error_code = models.CharField(max_length=64, blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            # DB-level overlap lock. Holds even when the Redis lock is
            # unavailable, and makes a double-scheduled beat job fail loudly
            # instead of interleaving two writers.
            models.UniqueConstraint(
                fields=["source"],
                condition=Q(status=SyncStatus.RUNNING.value),
                name="uniq_running_sync_run_per_source",
            ),
        ]
        indexes = [
            models.Index(fields=["source", "-started_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.source} {self.status} @ {self.started_at:%Y-%m-%d %H:%M}"


class ModelAlias(models.Model):
    """A human-confirmed identity mapping, consulted before any inference.

    Seeded from `aliases.py` by migration 0002 and editable in the admin, so a
    fix found during unmatched review is applied by the *next refresh* -- no
    deploy, no code change, no backfill. The ladder reads this table when it
    rebuilds the match set, so the resulting join is stored like any other and
    the read path stays a pure database query.
    """

    source = models.CharField(max_length=32, choices=Source.choices)
    #: Empty for source-wide aliases (e.g. AA name -> key).
    category = models.CharField(max_length=32, blank=True, default="")
    raw_name = models.CharField(max_length=255)
    canonical_key = models.CharField(max_length=255)
    note = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source", "category", "raw_name"]
        verbose_name_plural = "Model aliases"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "category", "raw_name"],
                name="uniq_model_alias_identity",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.raw_name} -> {self.canonical_key}"
