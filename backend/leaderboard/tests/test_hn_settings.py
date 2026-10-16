"""The Hacker News defaults exist in two places, and must not drift.

`constants.hn_config()` has to be usable **without settings configured**, because
`api/` reads it on the request path and importing the service layer from a view is
forbidden. So each tunable is declared twice: once as a `DEFAULT_HN_*` in
`constants.py`, and once as a `LEADERBOARD_HN_*` environment setting in
`settings.py`. That is the precedent `DEFAULT_STALE_AFTER_SECONDS` set.

This module is what makes the duplication safe. Without it, changing a default in
one file and not the other would produce a value that depends on whether Django
happened to be configured -- which is exactly the class of bug that is invisible
until production.
"""

from __future__ import annotations

import pytest
from django.conf import settings

from leaderboard import constants

#: `(constants default, settings name)`. The mapping is written out rather than
#: derived so that a *new* tunable added to one file and not the other shows up as
#: a missing entry here rather than passing silently.
DEFAULTS = [
    (constants.DEFAULT_HN_ENABLED, "LEADERBOARD_HN_ENABLED"),
    (constants.DEFAULT_HN_BASE_URL, "LEADERBOARD_HN_BASE_URL"),
    (constants.DEFAULT_HN_WINDOW_DAYS, "LEADERBOARD_HN_WINDOW_DAYS"),
    (constants.DEFAULT_HN_WINDOW_SLICE_DAYS, "LEADERBOARD_HN_WINDOW_SLICE_DAYS"),
    (constants.DEFAULT_HN_MIN_POINTS, "LEADERBOARD_HN_MIN_POINTS"),
    (constants.DEFAULT_HN_MIN_COMMENTS, "LEADERBOARD_HN_MIN_COMMENTS"),
    (constants.DEFAULT_HN_SWEEP_MIN_POINTS, "LEADERBOARD_HN_SWEEP_MIN_POINTS"),
    (constants.DEFAULT_HN_SWEEP_MIN_COMMENTS, "LEADERBOARD_HN_SWEEP_MIN_COMMENTS"),
    (constants.DEFAULT_HN_COMMENT_WEIGHT, "LEADERBOARD_HN_COMMENT_WEIGHT"),
    (constants.DEFAULT_HN_MAX_TREES_PER_RUN, "LEADERBOARD_HN_MAX_TREES_PER_RUN"),
    (constants.DEFAULT_HN_KEYWORD_QUERY_BUDGET, "LEADERBOARD_HN_KEYWORD_QUERY_BUDGET"),
    (constants.DEFAULT_HN_HITS_PER_PAGE, "LEADERBOARD_HN_HITS_PER_PAGE"),
    (constants.DEFAULT_HN_MAX_PAGE, "LEADERBOARD_HN_MAX_PAGE"),
    (constants.DEFAULT_HN_MAX_COMMENTS, "LEADERBOARD_HN_MAX_COMMENTS"),
    (constants.DEFAULT_HN_MAX_STORED_COMMENTS, "LEADERBOARD_HN_MAX_STORED_COMMENTS"),
    (constants.DEFAULT_HN_MAX_ITEM_BYTES, "LEADERBOARD_HN_MAX_ITEM_BYTES"),
    (constants.DEFAULT_HN_TREE_TIMEOUT_SECONDS, "LEADERBOARD_HN_TREE_TIMEOUT_SECONDS"),
    (constants.DEFAULT_HN_RUN_BUDGET_SECONDS, "LEADERBOARD_HN_RUN_BUDGET_SECONDS"),
    (
        constants.DEFAULT_HN_MAX_INLINE_RETRY_AFTER_SECONDS,
        "LEADERBOARD_HN_MAX_INLINE_RETRY_AFTER_SECONDS",
    ),
    (constants.DEFAULT_HN_STALE_AFTER_SECONDS, "LEADERBOARD_HN_STALE_AFTER_SECONDS"),
]


@pytest.mark.parametrize(("constant", "setting"), DEFAULTS)
def test_the_two_defaults_agree(constant, setting):
    assert getattr(settings, setting) == constant, (
        f"{setting} in settings.py and its DEFAULT_HN_* twin in constants.py "
        "disagree; the effective value would then depend on whether Django was "
        "configured, which is how this drifts unnoticed"
    )


def test_hn_config_reads_every_setting_it_declares():
    """Every field on `HNConfig` has to come from somewhere.

    A field left out of the constructor would silently keep whatever the dataclass
    default was -- and a frozen dataclass with no default raises, so the failure
    would be at import rather than here. This pins the mapping explicitly.
    """
    cfg = constants.hn_config()

    assert cfg.enabled == settings.LEADERBOARD_HN_ENABLED
    assert cfg.base_url == settings.LEADERBOARD_HN_BASE_URL
    assert cfg.window_days == settings.LEADERBOARD_HN_WINDOW_DAYS
    assert cfg.window_slice_days == settings.LEADERBOARD_HN_WINDOW_SLICE_DAYS
    assert cfg.min_points == settings.LEADERBOARD_HN_MIN_POINTS
    assert cfg.min_comments == settings.LEADERBOARD_HN_MIN_COMMENTS
    assert cfg.sweep_min_points == settings.LEADERBOARD_HN_SWEEP_MIN_POINTS
    assert cfg.sweep_min_comments == settings.LEADERBOARD_HN_SWEEP_MIN_COMMENTS
    assert cfg.comment_weight == settings.LEADERBOARD_HN_COMMENT_WEIGHT
    assert cfg.max_trees_per_run == settings.LEADERBOARD_HN_MAX_TREES_PER_RUN
    assert cfg.keyword_query_budget == settings.LEADERBOARD_HN_KEYWORD_QUERY_BUDGET
    assert cfg.hits_per_page == settings.LEADERBOARD_HN_HITS_PER_PAGE
    assert cfg.max_page == settings.LEADERBOARD_HN_MAX_PAGE
    assert cfg.max_comments == settings.LEADERBOARD_HN_MAX_COMMENTS
    assert cfg.max_stored_comments == settings.LEADERBOARD_HN_MAX_STORED_COMMENTS
    assert cfg.max_item_bytes == settings.LEADERBOARD_HN_MAX_ITEM_BYTES
    assert cfg.tree_timeout_seconds == settings.LEADERBOARD_HN_TREE_TIMEOUT_SECONDS
    assert cfg.run_budget_seconds == settings.LEADERBOARD_HN_RUN_BUDGET_SECONDS
    assert (
        cfg.max_inline_retry_after_seconds
        == settings.LEADERBOARD_HN_MAX_INLINE_RETRY_AFTER_SECONDS
    )
    assert cfg.stale_after_seconds == settings.LEADERBOARD_HN_STALE_AFTER_SECONDS


def test_a_settings_override_wins(settings):
    """`hn_config()` reads settings, not the constants, when a value is set."""
    settings.LEADERBOARD_HN_WINDOW_DAYS = 3

    assert constants.hn_config().window_days == 3


def test_constants_requires_no_configured_settings_to_import():
    """The property the whole duplication exists for.

    `api/` reads these through `constants.hn_config()` on the request path, and a
    view must not be one import away from the service layer -- so importing
    `constants` has to work without Django settings configured. The way that is
    achieved is `from django.conf import settings` living *inside* the accessor
    rather than at module scope, and the observable consequence is that the module
    has no `settings` attribute at all.
    """
    from leaderboard import constants as module

    assert not hasattr(module, "settings")


def _hn_check_ids() -> set[str]:
    """Every check id the Hacker News validation owns."""
    return {
        "leaderboard.E006",
        "leaderboard.E007",
        "leaderboard.E008",
        "leaderboard.E009",
        "leaderboard.E010",
        "leaderboard.E011",
        "leaderboard.E012",
        "leaderboard.E013",
        "leaderboard.E014",
        "leaderboard.E015",
        "leaderboard.W002",
    }


class TestChecks:
    """`checks.py` catches the relationships, not just the individual values."""

    def test_the_default_configuration_raises_nothing(self):
        from django.core.checks import run_checks

        ids = {problem.id for problem in run_checks()}

        assert ids & _hn_check_ids() == set()

    def test_a_pagination_configuration_past_the_ceiling_is_an_error(self, settings):
        from django.core.checks import run_checks

        settings.LEADERBOARD_HN_HITS_PER_PAGE = 500
        settings.LEADERBOARD_HN_MAX_PAGE = 500

        ids = {problem.id for problem in run_checks()}

        assert "leaderboard.E009" in ids

    def test_a_stored_cap_above_the_refusal_is_an_error(self, settings):
        """Otherwise the truncation cap could never bind, because every thread
        would already have been refused."""
        from django.core.checks import run_checks

        settings.LEADERBOARD_HN_MAX_COMMENTS = 10
        settings.LEADERBOARD_HN_MAX_STORED_COMMENTS = 100

        ids = {problem.id for problem in run_checks()}

        assert "leaderboard.E011" in ids

    def test_a_slice_wider_than_the_window_is_an_error(self, settings):
        """The window would be partly unqueried while the slices looked exhaustive."""
        from django.core.checks import run_checks

        settings.LEADERBOARD_HN_WINDOW_DAYS = 7
        settings.LEADERBOARD_HN_WINDOW_SLICE_DAYS = 30

        ids = {problem.id for problem in run_checks()}

        assert "leaderboard.E007" in ids

    def test_a_sweep_floor_above_the_window_floor_is_an_error(self, settings):
        """The sweep exists to reach what the window's floor excludes, so a higher
        sweep floor makes the stream unable to find anything new -- while still
        spending its requests every hour."""
        from django.core.checks import run_checks

        settings.LEADERBOARD_HN_SWEEP_MIN_POINTS = 500

        ids = {problem.id for problem in run_checks()}

        assert "leaderboard.E015" in ids

    def test_a_negative_sweep_floor_is_an_error(self, settings):
        from django.core.checks import run_checks

        settings.LEADERBOARD_HN_SWEEP_MIN_COMMENTS = -1

        ids = {problem.id for problem in run_checks()}

        assert "leaderboard.E014" in ids

    def test_a_negative_floor_is_an_error(self, settings):
        from django.core.checks import run_checks

        settings.LEADERBOARD_HN_MIN_POINTS = -1

        ids = {problem.id for problem in run_checks()}

        assert "leaderboard.E012" in ids

    def test_a_non_positive_window_is_an_error(self, settings):
        from django.core.checks import run_checks

        settings.LEADERBOARD_HN_WINDOW_DAYS = 0

        ids = {problem.id for problem in run_checks()}

        assert "leaderboard.E006" in ids

    def test_a_zero_tree_budget_warns_rather_than_failing(self, settings):
        """It is a legitimate way to run discovery without trees, and the bank
        would hold threads with no comments -- worth saying, not worth refusing."""
        from django.core.checks import run_checks

        settings.LEADERBOARD_HN_MAX_TREES_PER_RUN = 0

        ids = {problem.id for problem in run_checks()}

        assert "leaderboard.W002" in ids
