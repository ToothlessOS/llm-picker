"""Turn Hacker News (Algolia) payloads into validated, typed values.

The counterpart of `validation.py` for the third source, and the same contract:
this is the only module that knows the shape of an upstream record, everything
downstream works with the `Parsed*` dataclasses, and a schema change breaks here
rather than half-writing a row.

**Tolerant on the fields we do not need, strict on the ones we do.** Algolia's
Hacker News index is undocumented and unversioned, so an added key must never
fail a run. But `objectID`/`id`, the title and the timestamps are load-bearing --
a story without them cannot be stored under a stable identity -- so their absence
is a `ValidationError` and a `validation_failed` anomaly, not a silent skip.

Two traversal decisions worth knowing, both in `parse_item_tree`:

* **Breadth-first, then document order.** The comment cap exists because a thread
  can carry thousands of comments; BFS at least guarantees that what survives is
  the *shape* of the discussion -- every top-level reply before any deep
  sub-thread -- rather than one branch followed to the bottom. It is also
  deterministic, so re-fetching a thread truncates identically.
* **The stored payload is a skeleton, not the tree.** The comments are rows in
  `HNComment`; duplicating megabytes of the same text into a JSON column would
  double the footprint to buy nothing. `raw_payload` keeps the story's own fields
  plus the comment key-set observed, which is what actually diagnoses drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from .hn_text import CleanedText, clean_comment_text
from .validation import ValidationError, as_int, as_text, require_mapping

#: Zero-padding for one `path` segment. Six digits allows 999,999 siblings, which
#: no Hacker News thread approaches, while keeping a 30-level path inside the
#: column's 255 characters.
PATH_SEGMENT_WIDTH = 6

#: The separator between path segments. Chosen because it cannot occur inside a
#: zero-padded integer, so a prefix test is unambiguous.
PATH_SEPARATOR = "."

#: Hostname prefixes dropped when deriving a story's `domain`. Hacker News shows
#: "github.com" for what a submitter typed as "www.github.com", so matching that
#: keeps the filter and the display in agreement. Only `www.` -- stripping more
#: would merge genuinely different hosts.
_DOMAIN_PREFIXES: tuple[str, ...] = ("www.",)


@dataclass(frozen=True)
class ParsedStoryHit:
    """One story, as the search API reported it.

    This is discovery metadata: it is what the ranking is computed from and what
    the refetch gate compares against. The comment bodies come separately, from
    `parse_item_tree`.
    """

    hn_id: int
    title: str
    url: str
    domain: str
    author: str
    points: int | None
    num_comments: int | None
    posted_at: datetime
    #: The hit verbatim, for provenance and drift forensics. Never exposed.
    raw: dict[str, Any]


@dataclass(frozen=True)
class ParsedComment:
    """One comment, with its position and its sanitized body."""

    hn_id: int
    parent_hn_id: int | None
    depth: int
    sibling_index: int
    path: str
    author: str
    text: CleanedText
    is_deleted: bool
    is_dead: bool
    points: int | None
    posted_at: datetime | None


@dataclass(frozen=True)
class ParsedTree:
    """A thread's comments, capped, plus what the cap cost."""

    comments: tuple[ParsedComment, ...]
    max_depth: int
    #: True when the upstream tree carried more nodes than we stored -- the cap,
    #: a node with no usable id, or a repeated id (the first occurrence is kept).
    #: Recorded on the thread so a truncated discussion never reads as a complete
    #: one.
    truncated: bool
    #: How many nodes the full tree held, before the cap and before duplicate ids
    #: were collapsed.
    total_nodes: int
    #: Diagnostics kept in `HNThread.raw_payload` -- the story's own fields and the
    #: set of keys observed on comment nodes. Small, and the thing that makes a
    #: schema change visible.
    skeleton: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Coercion
# --------------------------------------------------------------------------- #


def _as_datetime(raw: Mapping[str, Any]) -> datetime | None:
    """A UTC timestamp from either spelling Algolia publishes.

    `created_at_i` (unix seconds) is preferred over the ISO `created_at` string:
    both are present in practice, and the integer cannot be misread as local
    time by a parser that ignores the offset.
    """
    stamp = raw.get("created_at_i")
    parsed = as_int(stamp, field="created_at_i")
    if parsed is not None:
        try:
            return datetime.fromtimestamp(parsed, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValidationError(f"created_at_i is not a usable timestamp: {stamp!r}", field="created_at_i") from exc

    text = as_text(raw.get("created_at"))
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"created_at is not a timestamp: {text!r}", field="created_at") from exc
    # A naive value is UTC by construction: the API publishes "Z"-suffixed times.
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def domain_from_url(url: str) -> str:
    """The hostname of a submitted link, for display and filtering.

    Extracted at ingest so no reader parses URLs, and so the domain filter cannot
    disagree with what the UI shows. An unparseable or scheme-less URL yields an
    empty string rather than raising: a story with a malformed link is still a
    story.
    """
    if not url:
        return ""
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError:
        return ""
    if not host:
        return ""
    host = host.casefold()
    for prefix in _DOMAIN_PREFIXES:
        if host.startswith(prefix) and len(host) > len(prefix):
            return host[len(prefix) :]
    return host


def _story_id(raw: Mapping[str, Any]) -> int:
    """The numeric HN item id, from either spelling.

    Search hits publish it as the string `objectID`; the item endpoint publishes
    it as the integer `id`. Both are the same identity, and it is the upsert key,
    so neither may be missing.
    """
    for key in ("objectID", "id", "story_id"):
        value = raw.get(key)
        parsed = as_int(value, field=key)
        if parsed is not None:
            return parsed
    raise ValidationError("Hacker News record has no item id", field="objectID")


# --------------------------------------------------------------------------- #
# Stories
# --------------------------------------------------------------------------- #


def parse_story_hit(raw: Mapping[str, Any]) -> ParsedStoryHit:
    """Parse one entry of a `/search_by_date` `hits` array."""
    payload = require_mapping(raw, what="Hacker News hit")

    hn_id = _story_id(payload)
    title = as_text(payload.get("title") or payload.get("story_title"))
    if not title:
        raise ValidationError("Hacker News story has no title", field="title")

    posted_at = _as_datetime(payload)
    if posted_at is None:
        raise ValidationError("Hacker News story has no timestamp", field="created_at_i")

    url = as_text(payload.get("url") or payload.get("story_url"))

    return ParsedStoryHit(
        hn_id=hn_id,
        title=title,
        url=url,
        domain=domain_from_url(url),
        author=as_text(payload.get("author")),
        # `as_int` maps blank to None and refuses to invent a zero: a story whose
        # points HN has not published is unmeasured, which is not the same as a
        # story with none.
        points=as_int(payload.get("points"), field="points"),
        num_comments=as_int(payload.get("num_comments"), field="num_comments"),
        posted_at=posted_at,
        raw=dict(payload),
    )


# --------------------------------------------------------------------------- #
# Comment trees
# --------------------------------------------------------------------------- #


def _path(parent_path: str, sibling_index: int) -> str:
    segment = str(sibling_index).zfill(PATH_SEGMENT_WIDTH)
    return f"{parent_path}{PATH_SEPARATOR}{segment}" if parent_path else segment


def _is_deleted(payload: Mapping[str, Any], *, author: str, text_raw: Any) -> bool:
    """Did Hacker News withhold this comment's body?

    The API's own signals are inconsistent, so this reads the practical ones: a
    deleted comment arrives with no author or no text. It is stored anyway -- its
    replies survive, and dropping the row would orphan them.
    """
    if payload.get("deleted") is True:
        return True
    return not author or text_raw is None


def parse_item_tree(
    raw: Mapping[str, Any],
    *,
    max_stored_comments: int,
) -> ParsedTree:
    """Parse a `GET /items/{id}` response into its comments, breadth-first.

    The story node itself is not returned as a comment; its fields are echoed in
    `skeleton` for drift forensics.

    Comment ids are globally unique, so a payload that repeats one (malformed or
    transient upstream data) keeps its **first** breadth-first occurrence and
    drops the rest. Two `ParsedComment`s with one `hn_id` would make the comment
    upsert collide with the unique index, and would put the same comment at two
    positions in the stored tree.
    """
    payload = require_mapping(raw, what="Hacker News item")
    if max_stored_comments < 1:
        raise ValueError("max_stored_comments must be at least 1")

    #: Breadth-first frontier of (raw node, parent_hn_id, depth, sibling_index).
    #: A list used as a queue, with an index cursor rather than `pop(0)` -- at a
    #: few thousand nodes the copies `pop(0)` makes are pure waste.
    queue: list[tuple[Mapping[str, Any], int | None, int, int, str]] = []
    for index, child in enumerate(_children(payload)):
        queue.append((child, None, 0, index, ""))

    comments: list[ParsedComment] = []
    comment_keys: set[str] = set()
    seen_ids: set[int] = set()
    max_depth = 0
    cursor = 0

    while cursor < len(queue):
        node, parent_hn_id, depth, sibling_index, parent_path = queue[cursor]
        cursor += 1
        comment_keys.update(str(key) for key in node)

        # The cap is checked before appending, but the walk continues so
        # `total_nodes` counts the *whole* tree -- which is what makes `truncated`
        # a fact rather than a guess. Descendants of a skipped node are not
        # enqueued at all: without the parent's row there is nothing to hang them
        # from, and storing them would mean inventing a depth.
        if len(comments) >= max_stored_comments or _is_skipped(node):
            continue

        node_id = _node_id(node)
        # The first occurrence is canonical. A duplicate's children are not
        # enqueued: the first copy already queued them, and re-walking them would
        # let one sub-thread sit at two paths -- or, with a self-referential
        # payload, keep growing the queue forever.
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)

        comments.append(_parse_comment(node, parent_hn_id, depth, sibling_index, parent_path))
        max_depth = max(max_depth, depth)

        node_path = _path(parent_path, sibling_index)
        for index, child in enumerate(_children(node)):
            queue.append((child, node_id, depth + 1, index, node_path))

    total_nodes = _count_nodes(payload)
    return ParsedTree(
        comments=tuple(comments),
        max_depth=max_depth,
        truncated=len(comments) < total_nodes,
        total_nodes=total_nodes,
        skeleton={
            "story": {key: value for key, value in payload.items() if key != "children"},
            "comment_keys": sorted(comment_keys),
        },
    )


def _children(node: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """The node's children, tolerating a missing or malformed list.

    A comment whose `children` is absent is a leaf; one whose `children` is not a
    list at all is treated the same way rather than failing the thread, because
    losing one sub-thread is better than losing the discussion.
    """
    raw = node.get("children")
    if not isinstance(raw, list):
        return ()
    return tuple(child for child in raw if isinstance(child, Mapping))


def _node_id(node: Mapping[str, Any]) -> int:
    """A comment's numeric id, or 0 when the payload omits it.

    Only used to set `parent_hn_id`, so a missing id degrades to "parent unknown"
    rather than failing the whole tree -- the child is still stored and still
    carries its own id, which is what identity rests on.
    """
    parsed = as_int(node.get("id"), field="id")
    return parsed if parsed is not None else 0


def _is_skipped(node: Mapping[str, Any]) -> bool:
    """Nodes with no usable identity cannot become rows.

    A node without an `id` has no upsert key, so storing it would create a new
    duplicate row on every refresh.
    """
    return as_int(node.get("id"), field="id") is None


def _count_nodes(root: Mapping[str, Any]) -> int:
    """Total comments in the tree, walked iteratively.

    Iterative rather than recursive: Hacker News threads nest deeply enough that a
    recursive walk is a stack-overflow risk on hostile input, and this runs on
    every thread of every run.
    """
    total = 0
    stack: list[Mapping[str, Any]] = list(_children(root))
    while stack:
        node = stack.pop()
        total += 1
        stack.extend(_children(node))
    return total


def _parse_comment(
    node: Mapping[str, Any],
    parent_hn_id: int | None,
    depth: int,
    sibling_index: int,
    parent_path: str,
) -> ParsedComment:
    author = as_text(node.get("author"))
    text_raw = node.get("text")

    return ParsedComment(
        hn_id=_node_id(node),
        parent_hn_id=parent_hn_id,
        depth=depth,
        sibling_index=sibling_index,
        path=_path(parent_path, sibling_index),
        author=author,
        text=clean_comment_text(text_raw),
        is_deleted=_is_deleted(node, author=author, text_raw=text_raw),
        is_dead=bool(node.get("dead", False)),
        points=as_int(node.get("points"), field="points"),
        posted_at=_as_datetime(node),
    )


__all__ = [
    "PATH_SEGMENT_WIDTH",
    "PATH_SEPARATOR",
    "ParsedComment",
    "ParsedStoryHit",
    "ParsedTree",
    "domain_from_url",
    "parse_item_tree",
    "parse_story_hit",
]
