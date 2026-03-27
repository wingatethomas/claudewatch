"""Guide pane — static getting started content."""

from __future__ import annotations

from AppKit import NSView

from claudewatch.ui.components.composites.guide import build_guide
from claudewatch.ui.preferences.panes.common import create_pane_stack

_SECTIONS = [
    (
        "Getting Started",
        [
            "ClaudeWatch lives in your menu bar — click the icon to see all running Claude Code sessions.",
            "Sessions are grouped by status: Attention (needs input), Working, and Idle.",
        ],
    ),
    (
        "Focus a Session",
        [
            "Click any session to instantly focus its terminal window.",
            "Works with Terminal.app, VS Code, PyCharm, and tmux.",
        ],
    ),
    (
        "Session Actions",
        [
            "Hover over a session to see action buttons: Activity, Bookmark, and Quit.",
            "Activity shows a timeline of messages, tool calls, and responses.",
        ],
    ),
    (
        "Bookmarks",
        [
            "Bookmark a session to save it for later — find it in the Bookmarks submenu.",
            "Add a note when bookmarking to remind yourself what you were working on.",
        ],
    ),
    (
        "Notifications",
        [
            "Get notified when a session needs attention (e.g. tool approval).",
            "Configure notification sound and behavior in Settings.",
        ],
    ),
    (
        "Permissions",
        [
            "Accessibility — required to focus terminal windows when you click a session.",
            "Automation (Terminal) — required to list and control Terminal.app windows.",
            "All other permission prompts (Photos, Music, etc.) can be safely denied.",
        ],
    ),
]


def build_guide_pane(delegate: object, w: float, h: float) -> NSView:  # noqa: ARG001
    """Build the Guide pane using VStack + guide composite."""
    stack = create_pane_stack("Guide", w)

    guide_content_h = h - stack.content_height - 20
    guide_view = build_guide(sections=_SECTIONS, width=w - 24, height=guide_content_h)
    stack.add(guide_view, height=guide_content_h)

    return stack.to_view(min_height=h)
