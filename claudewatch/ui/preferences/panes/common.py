"""Shared constants and helpers for preference panes.

All panes MUST use these values for consistent layout.
"""

from AppKit import NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.layout import VStack
from claudewatch.ui.components.tokens import Font, Spacing
from claudewatch.ui.components.widgets.labels import pane_title, secondary_label
from claudewatch.ui.theme import theme

# Standard pane layout — derived from design tokens
PANE_PADDING = Spacing.MD  # 12 — top/bottom padding inside pane
PANE_SPACING = Spacing.SM  # 8 — gap between header and content
CONTENT_PADDING = Spacing.XL  # 24 — horizontal padding for content

# Title height (fixed)
_TITLE_H = 24


def create_pane_stack(title: str, width: float) -> VStack:
    """Create a VStack pre-configured with the standard pane header.

    Every pane should start with this instead of manually creating VStack.
    Returns a VStack with the title already added.
    """
    stack = VStack(width=width, padding=PANE_PADDING, spacing=PANE_SPACING)
    stack.add(pane_title(title), height=_TITLE_H)
    return stack


def create_pane(title: str, w: float, h: float, subtitle: str = "") -> tuple[NSView, float]:
    """Create a pane view with a standard header. Returns (view, content_top_y).

    For panes that need manual layout below the header (e.g. scroll views).
    content_top_y is the y position where content should start (below header).
    """
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    header_y = h - PANE_PADDING - _TITLE_H
    title_label = pane_title(title)
    title_label.setFrame_(NSMakeRect(CONTENT_PADDING, header_y, w - CONTENT_PADDING * 2, _TITLE_H))
    view.addSubview_(title_label)

    content_y = header_y - PANE_SPACING
    if subtitle:
        _sub_h = 14
        content_y -= _sub_h
        sub = secondary_label(subtitle, size=Font.SMALL)
        sub.setTextColor_(theme.tertiary)
        sub.setFrame_(NSMakeRect(CONTENT_PADDING, content_y, w - CONTENT_PADDING * 2, _sub_h))
        view.addSubview_(sub)
        content_y -= PANE_SPACING

    return view, content_y
