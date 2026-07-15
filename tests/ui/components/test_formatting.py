"""Tests for the shared UI formatting helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from claudewatch.ui.components.formatting import (
    BOOKMARK_NOTE_LIMIT,
    SESSION_DETAIL_LIMIT,
    SUMMARY_TITLE_LIMIT,
    relative_time,
    truncate,
)


def _iso(ago: timedelta) -> str:
    return (datetime.now(tz=UTC) - ago).isoformat()


class TestRelativeTime:
    def test_just_now(self) -> None:
        assert relative_time(_iso(timedelta(seconds=30))) == "just now"

    def test_minutes_ago(self) -> None:
        assert relative_time(_iso(timedelta(minutes=5))) == "5m ago"

    def test_hours_ago(self) -> None:
        assert relative_time(_iso(timedelta(hours=2))) == "2h ago"

    def test_yesterday(self) -> None:
        assert relative_time(_iso(timedelta(hours=30))) == "yesterday"

    def test_days_ago(self) -> None:
        assert relative_time(_iso(timedelta(days=3))) == "3d ago"

    def test_older_falls_back_to_date(self) -> None:
        dt = datetime.now(tz=UTC) - timedelta(days=30)
        assert relative_time(dt.isoformat()) == dt.strftime("%b %-d")

    def test_naive_timestamp_treated_as_utc(self) -> None:
        naive = (datetime.now(tz=UTC) - timedelta(minutes=10)).replace(tzinfo=None)
        assert relative_time(naive.isoformat()) == "10m ago"

    def test_invalid_input_returns_empty(self) -> None:
        assert relative_time("not-a-date") == ""
        assert relative_time("") == ""

    def test_menu_and_sessions_pane_share_the_formatter(self) -> None:
        from claudewatch.ui import menu_builder
        from claudewatch.ui.preferences.panes import sessions

        assert menu_builder.relative_time is relative_time
        assert sessions.relative_time is relative_time


def _old_detail_truncate(detail_text: str, _max_detail_total: int = 55) -> str:
    """Verbatim copy of the pre-consolidation menu_builder word-boundary logic."""
    if len(detail_text) > _max_detail_total:
        truncated = detail_text[: _max_detail_total - 1]
        last_space = truncated.rfind(" ")
        if last_space > _max_detail_total // 2:
            truncated = truncated[:last_space]
        detail_text = truncated + "…"
    return detail_text


class TestTruncate:
    def test_under_limit_unchanged(self) -> None:
        assert truncate("short", 10) == "short"

    def test_at_limit_unchanged(self) -> None:
        assert truncate("x" * 10, 10) == "x" * 10

    def test_over_limit_hard_cut_ends_with_ellipsis_at_limit(self) -> None:
        result = truncate("x" * 11, 10)
        assert result == "x" * 9 + "…"
        assert len(result) == 10

    def test_word_boundary_backs_up_to_last_space(self) -> None:
        assert truncate("alpha beta gamma delta", 15, word_boundary=True) == "alpha beta…"

    def test_word_boundary_ignores_space_before_half_limit(self) -> None:
        text = "ab " + "c" * 40
        assert truncate(text, 20, word_boundary=True) == text[:19] + "…"

    def test_word_boundary_matches_old_menu_builder_behavior(self) -> None:
        samples = [
            "",
            "fable 5",
            "fable 5 · short detail line",
            "x" * 55,
            "x" * 56,
            "fable 5 · fixing the login bug in the preferences pane window",
            "fable 5 · " + "supercalifragilisticexpialidocious" * 3,
            "word " * 20,
            "a" * 28 + " " + "b" * 40,
        ]
        for text in samples:
            assert truncate(text, 55, word_boundary=True) == _old_detail_truncate(text)

    def test_limits_cap_rendered_length(self) -> None:
        long_text = "y" * 200
        assert len(truncate(long_text, BOOKMARK_NOTE_LIMIT)) == BOOKMARK_NOTE_LIMIT
        assert len(truncate(long_text, SUMMARY_TITLE_LIMIT)) == SUMMARY_TITLE_LIMIT
        assert len(truncate(long_text, SESSION_DETAIL_LIMIT, word_boundary=True)) == SESSION_DETAIL_LIMIT
