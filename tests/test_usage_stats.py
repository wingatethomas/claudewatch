"""Tests for claudewatch.backend.services.usage_stats."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from claudewatch.backend.services.usage_stats import (
    _sum_range,
    format_stats_line,
    get_month_stats,
    get_today_stats,
    get_week_stats,
)


class TestSumRange:
    def test_sums_matching_dates(self):
        days = [
            {"date": "2026-03-20", "messageCount": 10, "sessionCount": 1, "toolCallCount": 5},
            {"date": "2026-03-21", "messageCount": 20, "sessionCount": 2, "toolCallCount": 10},
            {"date": "2026-03-22", "messageCount": 30, "sessionCount": 3, "toolCallCount": 15},
        ]
        result = _sum_range(days, "2026-03-20", "2026-03-21")
        assert result == {"messages": 30, "sessions": 3, "tools": 15}

    def test_empty_range(self):
        result = _sum_range([], "2026-01-01", "2026-12-31")
        assert result == {"messages": 0, "sessions": 0, "tools": 0}

    def test_no_matching_dates(self):
        days = [{"date": "2025-01-01", "messageCount": 10, "sessionCount": 1, "toolCallCount": 5}]
        result = _sum_range(days, "2026-01-01", "2026-12-31")
        assert result == {"messages": 0, "sessions": 0, "tools": 0}


class TestFormatStatsLine:
    def test_all_nonzero(self):
        result = format_stats_line({"messages": 100, "sessions": 5, "tools": 42})
        assert "100 msgs" in result
        assert "5 sessions" in result
        assert "42 tools" in result

    def test_no_activity(self):
        assert format_stats_line({"messages": 0, "sessions": 0, "tools": 0}) == "No activity"

    def test_partial(self):
        result = format_stats_line({"messages": 50, "sessions": 0, "tools": 10})
        assert "50 msgs" in result
        assert "sessions" not in result
        assert "10 tools" in result

    def test_comma_formatting(self):
        result = format_stats_line({"messages": 1234, "sessions": 1, "tools": 5678})
        assert "1,234" in result
        assert "5,678" in result


class TestGetStats:
    def test_today_reads_from_file(self, tmp_path):
        stats_file = tmp_path / "stats-cache.json"
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        data = {
            "version": 2,
            "dailyActivity": [
                {"date": today, "messageCount": 42, "sessionCount": 2, "toolCallCount": 10},
            ],
        }
        stats_file.write_text(json.dumps(data))
        with patch("claudewatch.backend.services.usage_stats._STATS_PATH", str(stats_file)):
            result = get_today_stats()
        assert result["messages"] == 42

    def test_missing_file_returns_zeros(self, tmp_path):
        with (
            patch("claudewatch.backend.services.usage_stats._STATS_PATH", str(tmp_path / "nope.json")),
            patch("claudewatch.backend.services.usage_stats.get_history", return_value=[]),
        ):
            result = get_today_stats()
        assert result == {"messages": 0, "sessions": 0, "tools": 0}

    def test_week_sums_7_days(self, tmp_path):
        stats_file = tmp_path / "stats-cache.json"
        now = datetime.now(tz=UTC)
        days = []
        for i in range(10):
            d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            days.append({"date": d, "messageCount": 10, "sessionCount": 1, "toolCallCount": 5})
        data = {"version": 2, "dailyActivity": days}
        stats_file.write_text(json.dumps(data))
        with patch("claudewatch.backend.services.usage_stats._STATS_PATH", str(stats_file)):
            result = get_week_stats()
        assert result["messages"] == 70  # 7 days * 10

    def test_month_sums_30_days(self, tmp_path):
        stats_file = tmp_path / "stats-cache.json"
        now = datetime.now(tz=UTC)
        days = []
        for i in range(35):
            d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            days.append({"date": d, "messageCount": 1, "sessionCount": 1, "toolCallCount": 1})
        data = {"version": 2, "dailyActivity": days}
        stats_file.write_text(json.dumps(data))
        with patch("claudewatch.backend.services.usage_stats._STATS_PATH", str(stats_file)):
            result = get_month_stats()
        assert result["messages"] == 30  # 30 days
