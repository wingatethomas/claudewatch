"""Pure display-formatting helpers shared across UI surfaces. No service imports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

BOOKMARK_NOTE_LIMIT = 26  # 25 note chars + ellipsis
SESSION_DETAIL_LIMIT = 55
SUMMARY_TITLE_LIMIT = 50


def relative_time(iso_str: str) -> str:  # noqa: PLR0911
    """Format a timestamp as relative time."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        now = datetime.now(tz=UTC)
        delta = now - dt
        if delta < timedelta(minutes=1):
            return "just now"
        if delta < timedelta(hours=1):
            return f"{int(delta.total_seconds() / 60)}m ago"
        if delta < timedelta(hours=24):
            return f"{int(delta.total_seconds() / 3600)}h ago"
        if delta < timedelta(days=2):
            return "yesterday"
        if delta < timedelta(days=7):
            return f"{int(delta.days)}d ago"
        return dt.strftime("%b %-d")
    except (ValueError, TypeError):
        return ""


def truncate(text: str, limit: int, *, word_boundary: bool = False) -> str:
    """Cap text at limit chars, replacing the tail with an ellipsis when cut."""
    if len(text) <= limit:
        return text
    truncated = text[: limit - 1]
    if word_boundary:
        last_space = truncated.rfind(" ")
        if last_space > limit // 2:
            truncated = truncated[:last_space]
    return truncated + "…"
