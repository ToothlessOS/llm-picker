"""The HTML sanitizer is a security boundary, so it is tested like one.

Hacker News serves comment bodies as a small fixed subset of HTML, and this
module's output is shipped to the browser and rendered with
``dangerouslySetInnerHTML``. A tag or attribute that slips through is therefore a
live injection rather than a cosmetic defect -- which is why the cases below are
adversarial (scheme smuggling, event handlers, nested drop bypasses) rather than
merely illustrative.
"""

from __future__ import annotations

import pytest

from leaderboard.hn_text import (
    clean_comment_text,
    html_is_empty,
    plain_text_from,
    truncate_plain,
)

from bs4 import BeautifulSoup


class TestAllowedMarkupSurvives:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("<p>one</p><p>two</p>", "<p>one</p><p>two</p>"),
            ("<i>a</i> <em>b</em>", "<i>a</i> <em>b</em>"),
            ("<b>a</b> <strong>b</strong>", "<b>a</b> <strong>b</strong>"),
            ("<code>x = 1</code>", "<code>x = 1</code>"),
            ("<blockquote>quote</blockquote>", "<blockquote>quote</blockquote>"),
            ("<u>a</u> <s>b</s>", "<u>a</u> <s>b</s>"),
        ],
    )
    def test_permitted_tags_pass_through(self, raw, expected):
        assert clean_comment_text(raw).html == expected

    def test_an_unclosed_tag_is_closed_rather_than_dropped(self):
        """Hacker News genuinely emits these, so the sanitizer has to cope."""
        assert clean_comment_text("<b>unclosed").html == "<b>unclosed</b>"

    def test_a_link_keeps_its_href_and_gains_opener_protection(self):
        result = clean_comment_text('<a href="https://example.com/x">link</a>')
        assert 'href="https://example.com/x"' in result.html
        assert 'rel="nofollow noopener noreferrer"' in result.html

    def test_pre_whitespace_is_preserved_in_html(self):
        """The HTML projection is the one that has to be readable as code."""
        raw = "<pre>def f():\n    return 1</pre>"
        assert clean_comment_text(raw).html == raw


class TestUnknownTagsAreUnwrapped:
    """Prose must never be lost to a tag we did not anticipate."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("<div>keep <span>this</span> prose</div>", "keep this prose"),
            ("<table><tr><td>cell</td></tr></table>", "cell"),
            ("<h1>heading</h1>", "heading"),
            ("<section><article>article</article></section>", "article"),
        ],
    )
    def test_text_survives_the_tag(self, raw, expected):
        assert clean_comment_text(raw).html == expected


class TestNonContentIsRemoved:
    """Script, style and friends never hold prose, so their text must not appear."""

    @pytest.mark.parametrize(
        "raw",
        [
            "<script>alert(1)</script>tail",
            '<style>body{color:red}</style>tail',
            '<iframe src="https://evil.example">fallback</iframe>tail',
            "<object data='x'>fallback</object>tail",
            "<template><p>tpl</p></template>tail",
            "<noscript>enable js</noscript>tail",
            "<form><input value='x'><button>go</button></form>tail",
        ],
    )
    def test_subtree_is_dropped(self, raw):
        assert clean_comment_text(raw).html == "tail"

    def test_nesting_inside_a_dropped_subtree_does_not_raise(self):
        """`decompose` takes the subtree with it, so a later snapshot entry is
        already detached. Unwrapping a detached node raises -- regression guard."""
        assert clean_comment_text("<svg><script>alert(1)</script></svg>tail").html == "tail"

    def test_html_comments_are_extracted(self):
        """Not content, and a classic way to smuggle markup past an allowlist."""
        assert clean_comment_text("<!-- secret -->visible").html == "visible"


class TestAttributeAllowlist:
    @pytest.mark.parametrize(
        "raw",
        [
            '<img src=x onerror=alert(1)>',
            '<p onclick="alert(1)">x</p>',
            '<a href="https://e.com" onclick="alert(1)">x</a>',
        ],
    )
    def test_event_handlers_never_survive(self, raw):
        result = clean_comment_text(raw)
        assert "onerror" not in result.html
        assert "onclick" not in result.html
        assert "alert(1)" not in result.html

    def test_style_and_class_are_dropped(self):
        result = clean_comment_text('<p style="color:red" class="x">text</p>')
        assert result.html == "<p>text</p>"


class TestHrefSchemeValidation:
    """Checked by parsing, not by a string prefix -- so every spelling agrees."""

    @pytest.mark.parametrize(
        "href",
        [
            "javascript:alert(1)",
            "JaVaScRiPt:alert(1)",
            "  javascript:alert(1)",
            "java\tscript:alert(1)",
            "java\nscript:alert(1)",
            "vbscript:msgbox(1)",
            "data:text/html;base64,PHNjcmlwdD4=",
            "file:///etc/passwd",
            # Relative and scheme-less: HN publishes absolute URLs, so anything
            # else is either an attack or a relinking bug.
            "/relative/path",
            "example.com/x",
            "",
        ],
    )
    def test_dangerous_and_non_absolute_hrefs_are_removed(self, href):
        result = clean_comment_text(f'<a href="{href}">click</a>')
        assert "href" not in result.html
        # The link *text* survives: dropping the whole element would delete a word
        # from the sentence.
        assert "click" in result.html

    @pytest.mark.parametrize(
        "href", ["https://example.com", "http://example.com", "HTTPS://EXAMPLE.COM"]
    )
    def test_http_and_https_survive(self, href):
        assert "href" in clean_comment_text(f'<a href="{href}">click</a>').html


class TestEntitiesAndText:
    def test_entities_are_decoded_once(self):
        result = clean_comment_text("it&#x27;s an &amp; entity")
        assert result.text == "it's an & entity"
        # Decoded then re-escaped on output: one round trip, not two.
        assert result.html == "it's an &amp; entity"

    def test_plain_text_collapses_whitespace(self):
        assert clean_comment_text("<pre>a\n   b</pre>").text == "a b"

    def test_plain_text_does_not_merge_words_across_tags(self):
        """`get_text` with no separator would produce "ab" here."""
        assert clean_comment_text("<b>a</b><i>b</i>").text == "a b"

    def test_both_projections_agree_on_what_was_said(self):
        """A script's text must not reach one projection and not the other."""
        result = clean_comment_text("<script>alert(1)</script>real words")
        assert "real words" in result.html
        assert result.text == "real words"

    @pytest.mark.parametrize("raw", [None, "", "   ", "\n"])
    def test_blank_input_is_empty_not_an_error(self, raw):
        """A link submission has no body at all, which is normal."""
        result = clean_comment_text(raw)
        assert result.html == ""
        assert result.text == ""


class TestHtmlIsEmpty:
    @pytest.mark.parametrize("raw", ["", "<p></p>", "<br>"])
    def test_markup_without_readable_text_counts_as_empty(self, raw):
        assert html_is_empty(clean_comment_text(raw).html)

    def test_markup_with_text_does_not(self):
        assert not html_is_empty(clean_comment_text("<p>x</p>").html)


class TestTruncatePlain:
    def test_short_text_is_returned_unchanged(self):
        assert truncate_plain("short", 20) == "short"

    def test_cuts_at_a_word_boundary(self):
        assert truncate_plain("the quick brown fox jumps", 12) == "the quick…"

    def test_a_single_long_token_is_cut_rather_than_discarded(self):
        """Otherwise a comment that opens with a URL would truncate to nothing."""
        assert truncate_plain("averyveryverylongtoken", 8) == "averyver…"

    @pytest.mark.parametrize("limit", [0, -1])
    def test_a_non_positive_limit_is_a_no_op(self, limit):
        assert truncate_plain("anything", limit) == "anything"


class TestPlainTextFromIsReusable:
    def test_accepts_an_already_parsed_tree(self):
        """`html_is_empty` parses once and reuses this rather than reparsing."""
        soup = BeautifulSoup("<p>already clean</p>", "html.parser")
        assert plain_text_from(soup) == "already clean"
