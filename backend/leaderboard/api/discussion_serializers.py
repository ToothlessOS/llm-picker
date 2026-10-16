"""Response shaping for the discussion endpoints.

Plain functions returning dicts, matching `serializers.py` -- and the same three
rules hold: `null` never becomes `0` or `""`, optional blocks are present and
explicitly `null` so the frontend can destructure without a guard, and no raw
upstream payload crosses this boundary (`HNThread.raw_payload` and
`source_metadata` stop here).

One rule is specific to this source. **`text_html` is pre-sanitized at ingest**,
against a tag and attribute allowlist whose own tests cover the adversarial cases.
It is emitted as HTML on purpose, and it is the reason that sanitizer is a security
boundary rather than a formatting convenience: a consumer rendering it must not
re-escape it, and a consumer *not* rendering it should use `text_plain` instead.
Both are served so that the choice is the client's.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from ..constants import hn_config
from ..models import DiscussionTag, HNComment, HNThread, ProviderEntity
from .serializers import iso, text

# --------------------------------------------------------------------------- #
# Tags
# --------------------------------------------------------------------------- #


def tag_block(tag: DiscussionTag) -> dict[str, Any]:
    """One tag, with the alias that produced it.

    The provenance **is** the review record, exactly as `match_block` is for the
    model join: `matched_text` is the string that fired and `match_mode` the rule
    that let it, so "why is this thread tagged Anthropic?" is answerable from the
    response rather than from a re-run.
    """
    entity = tag.entity
    return {
        "slug": entity.slug,
        "label": entity.label,
        "kind": entity.kind,
        # The vendor a service rolls up to, so a client can group without a lookup.
        "vendor": entity.vendor.slug if entity.vendor is not None else None,
        "matched_text": tag.matched_text,
        "match_mode": tag.match_mode,
        "mentions": tag.mentions,
    }


def _entity_summary(tags: Iterable[DiscussionTag]) -> list[dict[str, Any]]:
    """The distinct entities across a set of tags, deduped for display.

    The unique constraints guarantee at most one tag per `(scope, entity)`, so
    deduplication is only needed when several scopes are merged -- and the chips a
    reader sees should name each entity once however many comments raised it.
    """
    seen: dict[str, dict[str, Any]] = {}
    for tag in tags:
        block = tag_block(tag)
        existing = seen.get(block["slug"])
        if existing is None:
            seen[block["slug"]] = block
            continue
        existing["mentions"] += block["mentions"]
    return sorted(seen.values(), key=lambda item: (-item["mentions"], item["slug"]))


# --------------------------------------------------------------------------- #
# Threads
# --------------------------------------------------------------------------- #


def thread_row(thread: HNThread, *, tags: Sequence[DiscussionTag] = ()) -> dict[str, Any]:
    """One row of `/discussions/`.

    `comments_stored` sits beside `num_comments` deliberately: when they differ,
    the gap is the thing worth seeing, and `tree_truncated` says whether it is the
    ingest cap that caused it.
    """
    return {
        "hn_id": thread.hn_id,
        "title": thread.title,
        "url": text(thread.url),
        "domain": text(thread.domain),
        "author": text(thread.author),
        "points": thread.points,
        "num_comments": thread.num_comments,
        "comments_stored": thread.comments_stored,
        "max_depth": thread.max_depth,
        "tree_truncated": thread.tree_truncated,
        "rank_score": thread.rank_score,
        "keywords": list(thread.relevance_terms or []),
        "posted_at": iso(thread.posted_at),
        "fetched_at": iso(thread.fetched_at),
        "last_synced_at": iso(thread.last_synced_at),
        "hn_url": hn_permalink(thread.hn_id),
        "entities": _entity_summary(tags),
        # Present only when a search was applied, so its absence means "not asked"
        # rather than "no matches".
        "matched_comment_count": getattr(thread, "matched_comment_count", None),
    }


def thread_detail(thread: HNThread, *, tags: Sequence[DiscussionTag] = ()) -> dict[str, Any]:
    """The `thread` block of `/discussions/{hn_id}/`."""
    row = thread_row(thread, tags=tags)
    # `matched_comment_count` is an annotation only the list endpoint adds.
    row.pop("matched_comment_count", None)
    row["window_days"] = hn_config().window_days
    return row


def hn_permalink(hn_id: int) -> str:
    """The canonical Hacker News URL for an item.

    Built here rather than stored: it is derivable from the id, and a stored copy
    would be one more field that can disagree with the id it came from.
    """
    return f"https://news.ycombinator.com/item?id={hn_id}"


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #


def comment_row(
    comment: HNComment,
    *,
    children_count: int = 0,
    tags: Sequence[DiscussionTag] = (),
) -> dict[str, Any]:
    """One node of a discussion tree.

    Emitted in a **flat** list ordered by `path`, not as nested `children`. The
    consumer needs the flat form to build a tree anyway, and nesting makes two
    things ambiguous that matter: whether a childless node is childless or was cut
    by the ingest cap, and whether a missing parent means a deleted one. `depth`
    and `parent_hn_id` answer both; `path` gives the ordering.
    """
    return {
        "hn_id": comment.hn_id,
        "parent_hn_id": comment.parent_hn_id,
        "depth": comment.depth,
        "sibling_index": comment.sibling_index,
        "path": comment.path,
        "children_count": children_count,
        "author": text(comment.author),
        "points": comment.points,
        # Pre-sanitized at ingest -- safe to render as HTML. See the module docstring.
        "text_html": comment.text_html,
        "text_plain": comment.text_plain,
        "is_deleted": comment.is_deleted,
        "is_dead": comment.is_dead,
        "posted_at": iso(comment.posted_at),
        "hn_url": hn_permalink(comment.hn_id),
        "entities": _entity_summary(tags),
    }


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #


def entity_row(
    entity: ProviderEntity,
    *,
    thread_count: int = 0,
    aliases: Sequence[str] = (),
) -> dict[str, Any]:
    """One entry of the filter vocabulary.

    `aliases` is emitted so the index can show *what actually tags* a filter, which
    is the difference between "the Provider dropdown is empty" and "the Provider
    dropdown has 52 entries and this one matches on these five spellings".
    """
    return {
        "slug": entity.slug,
        "label": entity.label,
        "kind": entity.kind,
        "vendor": entity.vendor.slug if entity.vendor is not None else None,
        # The exact `LMArenaEntry.organization` spelling, when one exists -- the
        # bridge from a discussion back to the model tables.
        "lmarena_organization": text(entity.lmarena_organization),
        "aliases": list(aliases),
        "thread_count": thread_count,
        "note": text(entity.note),
    }


def entity_index_rows(
    entities: Sequence[ProviderEntity],
    *,
    counts: Mapping[int, int],
    aliases: Mapping[int, Sequence[str]],
) -> list[dict[str, Any]]:
    return [
        entity_row(
            entity,
            thread_count=counts.get(entity.pk, 0),
            aliases=aliases.get(entity.pk, ()),
        )
        for entity in entities
    ]


__all__ = [
    "comment_row",
    "entity_index_rows",
    "entity_row",
    "hn_permalink",
    "tag_block",
    "thread_detail",
    "thread_row",
]
