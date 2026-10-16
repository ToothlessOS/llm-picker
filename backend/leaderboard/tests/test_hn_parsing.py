"""Turning Hacker News payloads into typed values.

The rules under test are the ones a schema change would break silently: the item
id is the upsert key, the timestamps are the ordering, and the `path` is what the
API orders a thread by. Three of these cases exist because the payload is
undocumented and the failure mode is a plausible wrong answer rather than an
exception.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from leaderboard.hn_parsing import (
    PATH_SEGMENT_WIDTH,
    domain_from_url,
    parse_item_tree,
    parse_story_hit,
)
from leaderboard.tests.fakes import hn_comment, hn_item, hn_story_hit


class TestParseStoryHit:
    def test_reads_the_discovery_fields(self):
        story = parse_story_hit(
            hn_story_hit(
                45678901,
                "Muse Spark Open (meta.ai)",
                url="https://dev.meta.ai/resources/blog/x",
                points=646,
                num_comments=360,
                author="bigwheels",
                created_at_i=1_760_000_000,
            )
        )
        assert story.hn_id == 45678901
        assert story.title == "Muse Spark Open (meta.ai)"
        assert story.domain == "dev.meta.ai"
        assert story.points == 646
        assert story.num_comments == 360
        assert story.author == "bigwheels"
        assert story.posted_at == datetime.fromtimestamp(1_760_000_000, tz=timezone.utc)

    def test_prefers_the_integer_timestamp_over_the_iso_string(self):
        """`created_at_i` cannot be misread as local time; the string can."""
        story = parse_story_hit(
            hn_story_hit(1, "t", created_at_i=1_760_000_000, created_at="1999-01-01T00:00:00Z")
        )
        assert story.posted_at == datetime.fromtimestamp(1_760_000_000, tz=timezone.utc)
        assert story.posted_at.tzinfo is not None

    def test_falls_back_to_the_iso_string(self):
        story = parse_story_hit(
            hn_story_hit(1, "t", created_at_i=None, created_at="2026-10-15T09:12:00Z")
        )
        assert story.posted_at == datetime(2026, 10, 15, 9, 12, tzinfo=timezone.utc)

    def test_the_object_id_is_read_from_either_spelling(self):
        assert parse_story_hit(hn_story_hit(7, "t")).hn_id == 7
        assert parse_story_hit(hn_story_hit(7, "t", objectID=None, id=7)).hn_id == 7

    def test_a_missing_points_value_stays_none_and_never_becomes_zero(self):
        """The AA schema's rule, and it matters here for the same reason: a 0-point
        story and an unreported one are different facts."""
        assert parse_story_hit(hn_story_hit(1, "t", points=None)).points is None
        assert parse_story_hit(hn_story_hit(1, "t", points=0)).points == 0

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"objectID": None, "id": None, "story_id": None}, "objectID"),
            ({"title": ""}, "title"),
            ({"created_at_i": None, "created_at": None}, "created_at_i"),
            ({"created_at_i": "not-a-number", "created_at": None}, "created_at_i"),
        ],
    )
    def test_a_missing_load_bearing_field_is_a_validation_error(self, overrides, field):
        from leaderboard.validation import ValidationError

        payload = hn_story_hit(1, "title")
        payload.update(overrides)
        with pytest.raises(ValidationError) as excinfo:
            parse_story_hit(payload)
        assert excinfo.value.field == field

    def test_an_unknown_extra_key_is_tolerated(self):
        """Algolia adds fields, and an added field must never fail a run."""
        payload = hn_story_hit(1, "t")
        payload["some_new_field"] = {"nested": True}
        assert parse_story_hit(payload).hn_id == 1


class TestDomainFromUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://dev.meta.ai/x", "dev.meta.ai"),
            ("https://www.github.com/a/b", "github.com"),
            ("http://EXAMPLE.com/Path", "example.com"),
            ("https://example.com:8443/x", "example.com"),
            # Unparseable or scheme-less links still yield a story, so these must
            # degrade rather than raise.
            ("", ""),
            ("not a url", ""),
            ("/relative", ""),
        ],
    )
    def test_extracts_the_hostname(self, url, expected):
        assert domain_from_url(url) == expected

    def test_only_www_is_stripped(self):
        """Stripping more would merge hosts that are genuinely different."""
        assert domain_from_url("https://blog.example.com/x") == "blog.example.com"


class TestParseItemTree:
    def test_walks_breadth_first_so_the_shape_survives_a_cap(self):
        """BFS is what makes truncation keep the discussion's *shape* -- every
        top-level reply before any deep sub-thread -- instead of one branch
        followed to the bottom."""
        tree = parse_item_tree(_nested(), max_stored_comments=100)
        assert [comment.hn_id for comment in tree.comments] == [10, 20, 11, 12, 13]

    def test_assigns_depth_parent_and_sibling_index(self):
        tree = {comment.hn_id: comment for comment in parse_item_tree(_nested(), max_stored_comments=100).comments}

        assert tree[10].depth == 0
        assert tree[10].parent_hn_id is None
        assert tree[10].sibling_index == 0
        assert tree[20].sibling_index == 1
        assert tree[11].depth == 1
        assert tree[11].parent_hn_id == 10
        assert tree[13].depth == 2
        assert tree[13].parent_hn_id == 12

    def test_paths_sort_into_pre_order_display_order(self):
        """The API orders a thread by `path`, so a string sort has to reproduce a
        readable discussion: a comment, then its replies, then the next sibling."""
        tree = parse_item_tree(_nested(), max_stored_comments=100)
        ordered = [comment.hn_id for comment in sorted(tree.comments, key=lambda c: c.path)]

        assert ordered == [10, 11, 12, 13, 20]

    def test_a_path_segment_is_zero_padded_to_a_fixed_width(self):
        tree = parse_item_tree(_wide(12), max_stored_comments=100)
        assert tree.comments[10].path == str(10).zfill(PATH_SEGMENT_WIDTH)
        # Fixed width is what makes the lexical sort agree with the numeric one.
        assert tree.comments[10].path == "000010"
        assert tree.comments[2].path == "000002"

    def test_records_the_depth_it_reached(self):
        assert parse_item_tree(_nested(), max_stored_comments=100).max_depth == 2

    def test_the_cap_truncates_and_says_so(self):
        tree = parse_item_tree(_nested(), max_stored_comments=2)
        assert [comment.hn_id for comment in tree.comments] == [10, 20]
        assert tree.truncated is True
        # The *whole* tree's size, so `truncated` is a fact rather than a guess
        # that the payload merely looked big.
        assert tree.total_nodes == 5

    def test_within_the_cap_nothing_is_marked_truncated(self):
        tree = parse_item_tree(_nested(), max_stored_comments=100)
        assert tree.truncated is False
        assert tree.total_nodes == len(tree.comments)

    def test_a_child_of_a_dropped_node_is_not_stored(self):
        """Without the parent's row there is nothing to hang it from, and storing
        it would mean inventing a depth."""
        tree = parse_item_tree(_nested(), max_stored_comments=2)
        assert 11 not in {comment.hn_id for comment in tree.comments}

    @pytest.mark.parametrize("cap", [0, -1])
    def test_a_non_positive_cap_is_refused(self, cap):
        with pytest.raises(ValueError):
            parse_item_tree(_nested(), max_stored_comments=cap)

    def test_a_withheld_comment_is_stored_and_flagged(self):
        """Its replies survive, so dropping the row would orphan a live subthread."""
        tree = {comment.hn_id: comment for comment in parse_item_tree(_nested(), max_stored_comments=100).comments}

        assert tree[12].is_deleted is True
        assert tree[12].text.html == ""
        assert tree[13].is_deleted is False

    def test_a_comment_with_no_author_is_deleted(self):
        payload = hn_item(1, children=[hn_comment(5, author="", text="ghost")])
        tree = parse_item_tree(payload, max_stored_comments=10)
        assert tree.comments[0].is_deleted is True

    def test_a_node_without_an_id_is_skipped(self):
        """It has no upsert key, so storing it would duplicate on every refresh."""
        payload = hn_item(1, children=[hn_comment(5, id=None), hn_comment(6)])
        tree = parse_item_tree(payload, max_stored_comments=10)
        assert [comment.hn_id for comment in tree.comments] == [6]

    @pytest.mark.parametrize("children", [None, "not-a-list", {"a": 1}, 7])
    def test_malformed_children_are_treated_as_a_leaf(self, children):
        """Losing one sub-thread beats losing the discussion."""
        payload = hn_item(1, children=[hn_comment(5, children=children)])
        tree = parse_item_tree(payload, max_stored_comments=10)
        assert [comment.hn_id for comment in tree.comments] == [5]

    def test_the_story_node_is_not_itself_a_comment(self):
        tree = parse_item_tree(_nested(), max_stored_comments=100)
        assert 1 not in {comment.hn_id for comment in tree.comments}

    def test_the_skeleton_keeps_the_story_fields_and_the_comment_keys(self):
        """What actually diagnoses drift -- without duplicating every body."""
        tree = parse_item_tree(_nested(), max_stored_comments=100)

        assert tree.skeleton["story"]["title"] == "Thread"
        assert "children" not in tree.skeleton["story"]
        assert "author" in tree.skeleton["comment_keys"]
        assert "text" in tree.skeleton["comment_keys"]

    def test_sanitizes_each_body_on_the_way_in(self):
        payload = hn_item(1, children=[hn_comment(5, text="<p>hi</p><script>alert(1)</script>")])
        tree = parse_item_tree(payload, max_stored_comments=10)
        assert tree.comments[0].text.html == "<p>hi</p>"
        assert tree.comments[0].text.text == "hi"

    def test_parsing_the_same_payload_twice_is_identical(self):
        """Truncation has to be deterministic, or two runs would disagree about
        which comments a capped thread holds."""
        first = parse_item_tree(_nested(), max_stored_comments=3)
        second = parse_item_tree(_nested(), max_stored_comments=3)

        assert [(c.hn_id, c.path, c.depth) for c in first.comments] == [
            (c.hn_id, c.path, c.depth) for c in second.comments
        ]

    def test_an_empty_thread_yields_no_comments(self):
        tree = parse_item_tree(hn_item(1, children=[]), max_stored_comments=10)
        assert tree.comments == ()
        assert tree.truncated is False
        assert tree.max_depth == 0

    def test_deep_nesting_does_not_exhaust_the_stack(self):
        """Hacker News threads nest deeply; a recursive walk is a crash risk."""
        node = hn_comment(1000)
        for identifier in range(999, 0, -1):
            node = hn_comment(identifier, children=[node])

        tree = parse_item_tree(hn_item(1, children=[node]), max_stored_comments=5000)
        assert len(tree.comments) == 1000
        assert tree.max_depth == 999


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _nested() -> dict:
    """A thread with two top-level comments, a nested reply and a deleted one."""
    return hn_item(
        1,
        title="Thread",
        children=[
            hn_comment(
                10,
                author="a",
                text="<p>hi <b>there</b>",
                children=[
                    hn_comment(11, author="b", text="reply", children=[]),
                    hn_comment(
                        12,
                        author=None,
                        text=None,
                        children=[hn_comment(13, author="c", text="grandchild", children=[])],
                    ),
                ],
            ),
            hn_comment(20, author="d", text=None, children=[]),
        ],
    )


def _wide(count: int) -> dict:
    return hn_item(1, children=[hn_comment(identifier) for identifier in range(count)])
