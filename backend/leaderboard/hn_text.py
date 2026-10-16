"""Sanitize Hacker News comment markup.

Hacker News serves comment bodies as a small, fixed subset of HTML -- ``<p>``
between paragraphs, ``<a href>`` for links, ``<i>``/``<code>``/``<pre>`` for
formatting. Everything here exists because **this is a trust boundary**: the API
ships the result as HTML and the frontend renders it with
``dangerouslySetInnerHTML``, so a tag or attribute that slips through is a live
injection, not a cosmetic bug. Hence its own module and its own test file.

Two deliberate choices:

* **The parser is BeautifulSoup's, not ours.** A hand-rolled ``html.parser``
  subclass is a sanitizer, and hand-rolled sanitizers are how XSS happens. The
  stdlib ``html.parser`` *builder* is used, so there is no compiled dependency
  and no change to the image; ``lxml`` is unnecessary for a tag set this small.
* **Unknown tags are unwrapped; non-content elements are removed.** Those are two
  different questions and conflating them gets one of them wrong. ``<span>``,
  ``<div>`` or ``<table>`` may wrap *prose*, so dropping them would silently
  delete sentences -- they are unwrapped, and their text survives.
  ``<script>``/``<style>``/``<iframe>`` and friends never contain prose, so
  keeping their text would inject code into the reader's view; they are removed
  outright. HTML comments go the same way, being not content at all.

Whichever path a node takes, the serialization step escapes it, so nothing that
survives can execute -- it can only ever land as text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, Tag

#: Tags that survive. Anything else is unwrapped or dropped -- see
#: `DROPPED_TAGS`. Deliberately tiny: HN produces nothing outside this set, so a
#: tag appearing here that HN does not generate is an attack, not content.
ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "a",
        "i",
        "em",
        "b",
        "strong",
        "code",
        "pre",
        "br",
        "u",
        "s",
        "blockquote",
    }
)

#: Tags removed **with their whole subtree**, because their contents are never
#: prose the author intended a reader to see. Unwrapping these instead would paste
#: JavaScript or CSS into the comment body -- and would make the two projections
#: disagree, since BeautifulSoup's `get_text()` skips script and style content
#: while `decode_contents()` would not.
DROPPED_TAGS: frozenset[str] = frozenset(
    {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "applet",
        "template",
        "noscript",
        "svg",
        "math",
        "form",
        "input",
        "textarea",
        "select",
        "option",
        "button",
        "link",
        "meta",
        "base",
        "title",
        "head",
    }
)

#: Attributes that survive, per tag. Everything not named here is dropped --
#: including every ``on*`` handler, ``style`` and ``class``, which is why this is
#: an allowlist and not a list of things to remove.
ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "a": frozenset({"href"}),
}

#: URL schemes a link may keep. A relative or scheme-less href is refused too:
#: HN publishes absolute URLs, so anything else is either an attack or a
#: relinking bug, and neither is worth resolving against our own origin.
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

#: Applied to retained links. HN's own markup carries ``rel="nofollow"``; this
#: keeps that and adds the opener protections that matter once any consumer opens
#: the link in a new tab.
LINK_REL = "nofollow noopener noreferrer"

#: Any run of whitespace, for the plain-text projection.
_WHITESPACE_RUN = re.compile(r"\s+")


@dataclass(frozen=True)
class CleanedText:
    """Both projections of one comment body, from a single parse.

    ``html`` is the sanitized subset, safe to render as HTML and preserving
    ``<pre>`` whitespace. ``text`` is whitespace-collapsed, for search, list
    previews and screen readers -- code formatting lives in ``html`` only.
    """

    html: str
    text: str


EMPTY = CleanedText(html="", text="")


def clean_comment_text(raw: object) -> CleanedText:
    """Sanitize one HN ``text`` field.

    A ``None`` or blank input is the normal case for a link submission and for a
    comment whose body HN withheld, so it yields empty rather than raising.
    """
    if raw is None:
        return EMPTY
    source = str(raw)
    if not source.strip():
        return EMPTY

    soup = BeautifulSoup(source, "html.parser")

    # Comments are not content: they are never rendered, so keeping their text
    # would put words in the reader's mouth. (They are also a classic vector for
    # smuggling markup past a naive allowlist.)
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()

    # `find_all` returns a snapshot, so mutating the tree here is safe: the
    # children an `unwrap` releases are still in the tree and still appear later
    # in this list, where they are processed on their own terms.
    for tag in soup.find_all(True):
        # A `decompose` above takes a whole subtree with it, so a tag from this
        # snapshot can already be detached by the time the loop reaches it --
        # `<svg><script>` detaches the `<script>` when the `<svg>` goes. Unwrapping
        # a detached node raises, and the node is gone anyway, so skip it.
        if tag.parent is None or getattr(tag, "decomposed", False):
            continue
        if tag.name in DROPPED_TAGS:
            tag.decompose()
            continue
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue
        _clean_attributes(tag)

    html = soup.decode_contents().strip()
    return CleanedText(html=html, text=plain_text_from(soup))


def _clean_attributes(tag: Tag) -> None:
    """Reduce one allowed tag to its allowlisted attributes, validating values."""
    allowed = ALLOWED_ATTRIBUTES.get(tag.name, frozenset())

    for name in list(tag.attrs):
        if name not in allowed:
            del tag.attrs[name]

    href = tag.attrs.get("href")
    if href is None:
        return
    if not _is_safe_href(href):
        # Drop the attribute rather than the element, so the link text survives
        # as ordinary text instead of disappearing.
        del tag.attrs["href"]
        return
    tag.attrs["href"] = str(href).strip()
    tag.attrs["rel"] = LINK_REL


def _is_safe_href(href: object) -> bool:
    """Is this href an absolute http(s) URL?

    Checked by parsing rather than by string prefix, so that the tricks a prefix
    test misses -- ``java\\nscript:``, `` javascript:``, ``JaVaScRiPt:``, and
    ``&#106;avascript:`` (already decoded by the parser) -- all resolve to the
    same answer. A scheme that is not http(s) is refused however it is spelled.
    """
    if not isinstance(href, str):
        return False
    text = href.strip()
    if not text:
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    return parts.scheme.lower() in ALLOWED_SCHEMES and bool(parts.netloc)


def plain_text_from(soup: BeautifulSoup | Tag) -> str:
    """Whitespace-collapsed text of an already-sanitized tree.

    Derived from the **cleaned** tree rather than the raw input, so the two
    projections cannot disagree about what the comment says.
    """
    # A space separator, so `<b>a</b><i>b</i>` reads as "a b" rather than "ab".
    return _WHITESPACE_RUN.sub(" ", soup.get_text(" ")).strip()


def html_is_empty(html: str) -> bool:
    """True when sanitized markup carries no readable text.

    A body can sanitize to markup with nothing in it -- ``<p></p>``, or a comment
    whose entire content was an image tag. Callers use this to avoid rendering an
    empty paragraph, and it asks about *text* because the markup being present is
    not the same as there being something to read.
    """
    if not html:
        return True
    return not plain_text_from(BeautifulSoup(html, "html.parser"))


def truncate_plain(text: str, limit: int) -> str:
    """Cut plain text at a word boundary, appending an ellipsis when it was cut.

    Lives here so the list page and any future tree label truncate identically,
    and so the boundary rule (never mid-word, never longer than ``limit`` plus the
    ellipsis) is testable in one place.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    window = text[:limit]
    boundary = window.rfind(" ")
    # Only honour a boundary that keeps most of the window, so a single long token
    # (a URL, a hash) is cut rather than discarded.
    if boundary >= limit // 2:
        window = window[:boundary]
    return f"{window.rstrip()}…"


__all__ = [
    "ALLOWED_ATTRIBUTES",
    "ALLOWED_SCHEMES",
    "ALLOWED_TAGS",
    "DROPPED_TAGS",
    "CleanedText",
    "EMPTY",
    "clean_comment_text",
    "html_is_empty",
    "plain_text_from",
    "truncate_plain",
]
