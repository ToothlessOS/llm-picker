"""Report the records that did not make it into the joined data set.

This is the other half of the completeness rule. `/overview/` serves only
entries with an AA match; this command is how you find out *which* models that
excluded, *why*, and what a human could do about it.

The output is designed to be pasted into a `ModelAlias` row: `model_name` is the
verbatim upstream spelling, and `model_key` is the normalized key it failed to
resolve to. Both are exactly what the alias fields want.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from ...constants import CATEGORIES, Source, UnmatchedReason
from ...models import UnmatchedRecord

#: Fixed column widths for the table format, so the output stays aligned when
#: pasted into an issue or a doc.
_COLUMNS = (
    ("source", 20),
    ("category", 10),
    ("reason", 24),
    ("model_name", 46),
    ("model_key", 40),
)

_REASON_HELP = {
    UnmatchedReason.NO_LMARENA_MATCH.value: (
        "An AA record with no LMArena `agent` counterpart. Review whether AA "
        "simply lacks the model or our normalizer needs an alias."
    ),
    UnmatchedReason.NO_AA_MATCH.value: (
        "An LMArena `agent` model with no AA record at the same reasoning level. "
        "These are exactly the entries the completeness rule removes from "
        "/overview/ -- confirm whether AA lacks the model or an alias is needed."
    ),
    UnmatchedReason.NOT_IN_AGENT_SET.value: (
        "A document/search/webdev model absent from the `agent` split. Usually "
        "expected -- search-specialized models genuinely do not exist in agent."
    ),
    UnmatchedReason.AMBIGUOUS_MATCH.value: (
        "More than one candidate matched, so the ladder refused to guess. Read "
        "`detail`, then write an alias naming the intended target."
    ),
    UnmatchedReason.DUPLICATE_MODEL_NAME.value: (
        "Several upstream rows collapsed onto one normalized key. The winner was "
        "kept; the loser is listed here with both ranks."
    ),
    UnmatchedReason.VALIDATION_FAILED.value: (
        "A payload did not match the schema we expect. This usually means the "
        "upstream schema moved -- check `detail.field`."
    ),
    UnmatchedReason.MISSING_IDENTITY.value: (
        "No usable identity field (blank or missing name)."
    ),
}


class Command(BaseCommand):
    help = "List records that were excluded from the joined data set, with reasons."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--source", choices=[s.value for s in Source], default=None)
        parser.add_argument("--category", choices=list(CATEGORIES), default=None)
        parser.add_argument(
            "--reason", choices=[r.value for r in UnmatchedReason], default=None
        )
        parser.add_argument("--search", default=None, help="Substring of model_name or model_key.")
        parser.add_argument(
            "--all",
            action="store_true",
            help="Include records that stopped appearing upstream (is_current=False).",
        )
        parser.add_argument(
            "--format",
            choices=("table", "md", "json"),
            default="table",
            help="`md` emits a GitHub-flavoured Markdown table for pasting into a doc.",
        )
        parser.add_argument(
            "--limit", type=int, default=0, help="Truncate to N rows (0 = no limit)."
        )

    def handle(self, *args, **options) -> None:
        records = UnmatchedRecord.objects.all()

        if not options["all"]:
            records = records.filter(is_current=True)
        if options["source"]:
            records = records.filter(source=options["source"])
        if options["category"]:
            records = records.filter(category=options["category"])
        if options["reason"]:
            records = records.filter(reason=options["reason"])
        if options["search"]:
            from django.db.models import Q

            needle = options["search"]
            records = records.filter(
                Q(model_name__icontains=needle) | Q(model_key__icontains=needle)
            )

        records = records.order_by("source", "category", "reason", "model_key")
        rows = list(records.values(
            "source", "category", "reason", "model_key", "model_name",
            "organization", "occurrences", "is_current", "detail",
        ))

        limit = options["limit"]
        if limit and len(rows) > limit:
            self.stdout.write(f"(showing {limit} of {len(rows)} rows)")
            rows = rows[:limit]

        fmt = options["format"]
        if fmt == "json":
            self.stdout.write(json.dumps(rows, indent=2, default=str))
        elif fmt == "md":
            self._emit_markdown(rows)
        else:
            self._emit_table(rows)

        self._emit_summary(records)

    # -- renderers --------------------------------------------------------- #

    def _emit_table(self, rows) -> None:
        if not rows:
            self.stdout.write(self.style.SUCCESS("Nothing unmatched. Every record joined."))
            return

        header = "  ".join(name.ljust(width) for name, width in _COLUMNS)
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for row in rows:
            self.stdout.write(
                "  ".join(
                    str(row.get(name) or "").ljust(width)[:width]
                    for name, width in _COLUMNS
                )
            )

        # Anomalies carry the evidence a reviewer needs; print it under the
        # table rather than burying it in a column.
        detailed = [row for row in rows if row["detail"]]
        if detailed:
            self.stdout.write("")
            self.stdout.write("Detail:")
            for row in detailed:
                self.stdout.write(f"  {row['model_key']}: {json.dumps(row['detail'], default=str)}")

    def _emit_markdown(self, rows) -> None:
        if not rows:
            self.stdout.write("Nothing unmatched. Every record joined.")
            return
        self.stdout.write("| Source | Category | Reason | Model | Key | Seen | Detail |")
        self.stdout.write("| --- | --- | --- | --- | --- | --- | --- |")
        for row in rows:
            detail = json.dumps(row["detail"], default=str).replace("|", "\\|")
            self.stdout.write(
                f"| {row['source']} | {row['category'] or '—'} | {row['reason']} | "
                f"{row['model_name'] or '—'} | `{row['model_key']}` | "
                f"{row['occurrences']} | {detail or '—'} |"
            )

    def _emit_summary(self, records) -> None:
        by_reason: dict[str, int] = {}
        for reason in records.values_list("reason", flat=True):
            by_reason[reason] = by_reason.get(reason, 0) + 1

        if not by_reason:
            return

        self.stdout.write("")
        self.stdout.write("By reason:")
        for reason, count in sorted(by_reason.items(), key=lambda pair: -pair[1]):
            self.stdout.write(f"  {count:>6}  {reason}")
            help_text = _REASON_HELP.get(reason)
            if help_text:
                self.stdout.write(f"          {help_text}")
