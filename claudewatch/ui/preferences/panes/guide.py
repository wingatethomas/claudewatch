"""Guide pane — static getting started content."""

from __future__ import annotations

from AppKit import NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.composites.guide import build_guide
from claudewatch.ui.components.widgets.labels import pane_title

_PAD = 24

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
    """Build the Guide pane using the guide composite."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))

    y = h - 12 - 24
    title = pane_title("Guide")
    title.setFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, 24))
    view.addSubview_(title)
    y -= 8

    card_w = w - _PAD * 2
    card_h = y - 20
    guide_view = build_guide(sections=_SECTIONS, width=card_w, height=card_h)
    guide_view.setFrame_(NSMakeRect(_PAD, y - card_h, card_w, card_h))
    view.addSubview_(guide_view)

    return view
