"""Read Claude Code usage statistics from ~/.claude/stats-cache.json."""

import json
import logging
import os
from datetime import UTC, datetime, timedelta

log = logging.getLogger("claudewatch")

_STATS_PATH = os.path.expanduser("~/.claude/stats-cache.json")


def _load_daily_activity() -> list[dict]:
    """Load daily activity entries from the stats cache."""
    try:
        with open(_STATS_PATH) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    activity = data.get("dailyActivity", [])
    return activity if isinstance(activity, list) else []


def _sum_range(days: list[dict], start: str, end: str) -> dict[str, int]:
    """Sum messageCount, sessionCount, toolCallCount for dates in [start, end]."""
    messages = 0
    sessions = 0
    tools = 0
    for day in days:
        date = day.get("date", "")
        if start <= date <= end:
            messages += day.get("messageCount", 0)
            sessions += day.get("sessionCount", 0)
            tools += day.get("toolCallCount", 0)
    return {"messages": messages, "sessions": sessions, "tools": tools}


def get_today_stats() -> dict[str, int]:
    """Get today's usage stats."""
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    return _sum_range(_load_daily_activity(), today, today)


def get_week_stats() -> dict[str, int]:
    """Get this week's usage stats (last 7 days)."""
    now = datetime.now(tz=UTC)
    start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    return _sum_range(_load_daily_activity(), start, end)


def get_month_stats() -> dict[str, int]:
    """Get this month's usage stats (last 30 days)."""
    now = datetime.now(tz=UTC)
    start = (now - timedelta(days=29)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    return _sum_range(_load_daily_activity(), start, end)


def format_stats_line(stats: dict[str, int]) -> str:
    """Format stats as a compact one-line string."""
    parts = []
    if stats["messages"]:
        parts.append(f"{stats['messages']:,} msgs")
    if stats["sessions"]:
        parts.append(f"{stats['sessions']} sessions")
    if stats["tools"]:
        parts.append(f"{stats['tools']:,} tools")
    return " · ".join(parts) if parts else "No activity"
