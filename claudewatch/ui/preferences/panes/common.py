"""Shared constants and helpers for preference panes.

All panes MUST use these values for consistent layout.
"""

from AppKit import NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.layout import VStack
from claudewatch.ui.components.widgets.labels import pane_title, secondary_label

# Standard pane layout — used by every pane for consistent header positioning
PANE_PADDING = 12
PANE_SPACING = 8
CONTENT_PADDING = 24  # horizontal padding for content inside panes

# Fixed header height: padding(12) + title(24) + spacing(8) = 44
HEADER_HEIGHT = PANE_PADDING + 24 + PANE_SPACING


def create_pane_stack(title: str, width: float) -> VStack:
    """Create a VStack pre-configured with the standard pane header.

    Every pane should start with this instead of manually creating VStack.
    Returns a VStack with the title already added.
    """
    stack = VStack(width=width, padding=PANE_PADDING, spacing=PANE_SPACING)
    stack.add(pane_title(title), height=24)
    return stack


def create_pane(title: str, w: float, h: float, subtitle: str = "") -> tuple[NSView, float]:
    """Create a pane view with a standard header. Returns (view, content_top_y).

    For panes that need manual layout below the header (e.g. scroll views).
    content_top_y is the y position where content should start (below header).
    """
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    header_y = h - PANE_PADDING - 24
    title_label = pane_title(title)
    title_label.setFrame_(NSMakeRect(CONTENT_PADDING, header_y, w - CONTENT_PADDING * 2, 24))
    view.addSubview_(title_label)

    content_y = header_y - PANE_SPACING
    if subtitle:
        content_y -= 14
        sub = secondary_label(subtitle, size=11.0)
        from AppKit import NSColor

        sub.setTextColor_(NSColor.tertiaryLabelColor())
        sub.setFrame_(NSMakeRect(CONTENT_PADDING, content_y, w - CONTENT_PADDING * 2, 14))
        view.addSubview_(sub)
        content_y -= PANE_SPACING

    return view, content_y
