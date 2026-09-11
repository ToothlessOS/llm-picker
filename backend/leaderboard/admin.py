"""Admin registrations.

The admin is not decoration here -- it is the **alias review workflow**. The
unmatched report names the records that failed to join; a reviewer decides
whether two spellings are the same model, and writes a `ModelAlias`. The match
ladder consults this table when a refresh rebuilds the match set, so the decision
takes effect from the next refresh onwards: no deploy, no code change, no
backfill -- and `manage.py refresh_leaderboard --source=aa` applies it at once
rather than waiting for the schedule.

The source tables are read-mostly and are registered as read-only, so a stray
click in the admin cannot corrupt ingested data. `ModelAlias` is the one model
that is meant to be edited.

`SyncRun` is read-only for the same reason, plus a second one: its partial
unique index on `(source) WHERE status='running'` is what prevents two refreshes
overlapping, and a hand-edited status is exactly how that guarantee would be
broken.
"""

from django.contrib import admin

from .models import (
    LLMModel,
    LMArenaEntry,
    ModelAlias,
    ModelCreator,
    ModelMatch,
    SyncRun,
    UnmatchedRecord,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """View and search, but no add/change/delete."""

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ModelAlias)
class ModelAliasAdmin(admin.ModelAdmin):
    list_display = ("source", "category", "raw_name", "canonical_key", "note", "updated_at")
    list_filter = ("source", "category")
    search_fields = ("raw_name", "canonical_key", "note")
    ordering = ("source", "category", "raw_name")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (
            None,
            {
                "fields": ("source", "category", "raw_name", "canonical_key", "note"),
                "description": (
                    "Write <b>raw_name</b> exactly as it appears in the unmatched "
                    "report, and <b>canonical_key</b> as the agent-side normalized "
                    "key (lowercase, runs of non-alphanumerics replaced by '-', "
                    "parenthetical variants preserved: 'Claude Opus 5 (High)' "
                    "&rarr; 'claude-opus-5-high'). The match takes effect on the "
                    "next refresh -- run <code>manage.py refresh_leaderboard "
                    "--source=aa</code> to apply it now."
                ),
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(UnmatchedRecord)
class UnmatchedRecordAdmin(ReadOnlyAdmin):
    list_display = (
        "source",
        "category",
        "reason",
        "model_key",
        "model_name",
        "occurrences",
        "is_current",
        "last_seen_at",
    )
    list_filter = ("source", "reason", "is_current", "category")
    search_fields = ("model_key", "model_name", "organization")
    ordering = ("source", "category", "reason", "model_key")
    date_hierarchy = "last_seen_at"


@admin.register(SyncRun)
class SyncRunAdmin(ReadOnlyAdmin):
    list_display = (
        "source",
        "status",
        "started_at",
        "duration_ms",
        "records_seen",
        "records_created",
        "records_deactivated",
        "error_code",
    )
    list_filter = ("source", "status", "dry_run", "triggered_by")
    ordering = ("-started_at",)
    date_hierarchy = "started_at"


@admin.register(LLMModel)
class LLMModelAdmin(ReadOnlyAdmin):
    list_display = (
        "name",
        "slug",
        "creator",
        "intelligence_index",
        "cost_per_task",
        "is_retained",
        "is_active",
        "last_synced_at",
    )
    list_filter = ("is_retained", "is_active", "creator")
    search_fields = ("name", "slug", "aa_id")
    list_select_related = ("creator",)
    ordering = ("name",)


@admin.register(LMArenaEntry)
class LMArenaEntryAdmin(ReadOnlyAdmin):
    list_display = (
        "category",
        "model_name",
        "model_key",
        "rank",
        "metric_value",
        "sample_size",
        "in_agent_set",
        "is_active",
    )
    list_filter = ("category", "in_agent_set", "is_active", "metric_kind")
    search_fields = ("model_name", "model_key", "organization", "agent_key")
    ordering = ("category", "rank")


@admin.register(ModelMatch)
class ModelMatchAdmin(ReadOnlyAdmin):
    list_display = ("lmarena_entry", "model", "match_method", "confidence", "is_manual")
    list_filter = ("match_method", "is_manual")
    search_fields = ("lmarena_entry__model_name", "model__name", "matched_key")
    list_select_related = ("lmarena_entry", "model")


@admin.register(ModelCreator)
class ModelCreatorAdmin(ReadOnlyAdmin):
    list_display = ("name", "aa_id", "first_seen_at", "last_synced_at")
    search_fields = ("name", "aa_id")
    ordering = ("name",)
