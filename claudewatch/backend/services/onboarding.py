"""Onboarding tips — one-time getting-started notifications for feature discovery.

Delivers contextual tips via terminal-notifier the first time a user encounters
key features. Each tip is shown at most once; shown tip IDs are persisted in
~/.claude/claudewatch.json under ``onboarding_tips_shown``.
"""

import logging
import subprocess

from claudewatch.backend.repositories.config import get_setting, set_setting
from claudewatch.backend.services.notifications import TERMINAL_NOTIFIER

log = logging.getLogger("claudewatch")

TIPS: dict[str, dict[str, str]] = {
    "welcome": {
        "title": "Welcome to ClaudeWatch!",
        "message": "Click \u2726 in the menu bar to see your sessions.",
    },
    "attention": {
        "title": "Tip: Focus a session",
        "message": "Click a session to focus its window.",
    },
    "pin": {
        "title": "Tip: Pinned sessions",
        "message": "Pinned sessions can be resumed later from \u2605 Pinned.",
    },
    "hover": {
        "title": "Tip: Session actions",
        "message": "Hover a session for Activity, Pin, and Quit options.",
    },
}


def _shown_tips() -> list[str]:
    """Return the list of already-shown tip IDs."""
    tips = get_setting("onboarding_tips_shown")
    if isinstance(tips, list):
        return list(tips)
    return []


def _mark_shown(tip_id: str) -> None:
    """Persist *tip_id* as shown so it is never delivered again."""
    shown = _shown_tips()
    if tip_id not in shown:
        shown.append(tip_id)
        set_setting("onboarding_tips_shown", shown)


def is_tip_shown(tip_id: str) -> bool:
    """Check whether *tip_id* has already been delivered."""
    return tip_id in _shown_tips()


def show_tip(tip_id: str) -> bool:
    """Deliver an onboarding tip via terminal-notifier if not already shown.

    Returns ``True`` if the tip was actually sent, ``False`` otherwise.
    """
    if not TERMINAL_NOTIFIER:
        return False
    if is_tip_shown(tip_id):
        return False
    if not get_setting("notifications_enabled"):
        return False

    tip = TIPS.get(tip_id)
    if not tip:
        return False

    _mark_shown(tip_id)

    cmd = [
        TERMINAL_NOTIFIER,
        "-title",
        tip["title"],
        "-message",
        tip["message"],
        "-group",
        f"claudewatch-onboarding-{tip_id}",
        "-sender",
        "com.claudewatch",
    ]
    try:
        subprocess.run(  # noqa: S603
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        log.info("onboarding.tip_shown tip=%s", tip_id)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def get_session_count() -> int:
    """Return the cumulative number of unique sessions observed."""
    count = get_setting("onboarding_session_count")
    return int(count) if isinstance(count, (int, float)) else 0


def reset_tips() -> None:
    """Clear all shown tips so they can be replayed."""
    set_setting("onboarding_tips_shown", [])
    log.info("onboarding.tips_reset")


def replay_all_tips() -> None:
    """Reset and immediately deliver all tips."""
    reset_tips()
    for tip_id in TIPS:
        show_tip(tip_id)


def increment_session_count(n: int = 1) -> int:
    """Add *n* to the cumulative session counter and return the new total."""
    current = get_session_count()
    new_total = current + n
    set_setting("onboarding_session_count", new_total)
    return new_total
