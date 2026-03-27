"""Guide pane — static getting started content."""

from __future__ import annotations

import objc
from AppKit import NSButton, NSFont, NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.composites.guide import build_guide
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, create_pane

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

_BUTTON_H = 32


def build_guide_pane(delegate: object, w: float, h: float) -> NSView:
    """Build the Guide pane with fixed header + scrollable guide content + welcome button."""
    view, content_top = create_pane("Guide", w, h)

    # Welcome button at the bottom
    welcome_button = NSButton.alloc().initWithFrame_(NSMakeRect(CONTENT_PADDING, 8, 160, 24))
    welcome_button.setTitle_("Show Welcome Screen")
    welcome_button.setBezelStyle_(1)
    welcome_button.setFont_(NSFont.systemFontOfSize_(11.0))
    welcome_button.setTarget_(delegate)
    welcome_button.setAction_(objc.selector(delegate.showWelcome_, signature=b"v@:@"))
    view.addSubview_(welcome_button)

    # Guide content fills space between header and button
    guide_h = content_top - _BUTTON_H
    guide_view = build_guide(sections=_SECTIONS, width=w - CONTENT_PADDING * 2, height=guide_h)
    guide_view.setFrame_(NSMakeRect(CONTENT_PADDING, _BUTTON_H, w - CONTENT_PADDING * 2, guide_h))
    view.addSubview_(guide_view)

    return view
