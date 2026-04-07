"""Guide pane — static getting started content."""

from __future__ import annotations

import objc
from AppKit import NSButton, NSFont, NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.composites.guide import build_guide
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane

_SECTIONS = [
    (
        "Status Dots",
        [
            "The colored dots next to the menu bar icon show your sessions at a glance.",
            "Red = needs your attention (tool approval). Green = working. Yellow = idle.",
            "Click any session to jump straight to its terminal window.",
        ],
    ),
    (
        "Session Details",
        [
            "Expand a session to see its summary, token usage, and spawned agents.",
            "Summaries are generated automatically in the background using claude -p.",
            "Configure the model and effort level for summaries in Settings.",
        ],
    ),
    (
        "Bookmarks",
        [
            "Bookmark sessions you want to come back to — they persist across restarts.",
            "Bookmarked sessions appear in the Bookmarks section with a resume option.",
            "Add a note to remember what you were working on.",
        ],
    ),
    (
        "Security",
        [
            "The Security pane shows installed plugins, policies, and permissions.",
            "Get alerts when plugins are installed, policies change, or sessions run unrestricted.",
            "Manage permissions per project — remove stale rules or dangerous wildcards.",
        ],
    ),
    (
        "Notifications",
        [
            "Get alerted when Claude needs tool approval and you're in another app.",
            "Only fires when the session's terminal isn't in the foreground.",
            "Customize sound and behavior in Settings. Security alerts have their own sound.",
        ],
    ),
    (
        "Accessibility",
        [
            "Customize status dot colors for colorblind accessibility in Settings.",
            "Choose from Default, Blue-Orange, Blue-Yellow, or High Contrast schemes.",
        ],
    ),
    (
        "Permissions",
        [
            "Accessibility — needed to focus windows when you click a session.",
            "Automation (Terminal) — needed to detect which Terminal.app tabs are running Claude.",
            "You can safely deny any other permission prompts (Photos, Music, etc.).",
        ],
    ),
]

_BUTTON_H = 32


class GuidePane(BasePane):
    """Guide pane with static getting-started content and welcome button."""

    @property
    def title(self) -> str:
        return "Guide"

    def build_content(self, view: NSView, content_top: float) -> None:
        # Welcome button at the bottom
        welcome_button = NSButton.alloc().initWithFrame_(NSMakeRect(CONTENT_PADDING, 8, 160, 24))
        welcome_button.setTitle_("Show Welcome Screen")
        welcome_button.setBezelStyle_(1)
        welcome_button.setFont_(NSFont.systemFontOfSize_(11.0))
        welcome_button.setTarget_(self.delegate)
        welcome_button.setAction_(objc.selector(self.delegate.showWelcome_, signature=b"v@:@"))
        view.addSubview_(welcome_button)

        # Guide content fills space between header and button
        guide_h = content_top - _BUTTON_H
        guide_view = build_guide(sections=_SECTIONS, width=self.card_width, height=guide_h)
        guide_view.setFrame_(NSMakeRect(CONTENT_PADDING, _BUTTON_H, self.card_width, guide_h))
        view.addSubview_(guide_view)


# Legacy function interface for window.py
def build_guide_pane(delegate: object, w: float, h: float) -> NSView:
    """Build the Guide pane."""
    return GuidePane(delegate, w, h).build()
