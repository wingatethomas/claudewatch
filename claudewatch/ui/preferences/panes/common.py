"""Shared constants and helpers for preference panes.

All panes MUST use these values for consistent layout.
"""

from claudewatch.ui.components.layout import VStack
from claudewatch.ui.components.widgets.labels import pane_title

# Standard pane layout — used by every pane for consistent header positioning
PANE_PADDING = 12
PANE_SPACING = 8
CONTENT_PADDING = 24  # horizontal padding for content inside panes


def create_pane_stack(title: str, width: float) -> VStack:
    """Create a VStack pre-configured with the standard pane header.

    Every pane should start with this instead of manually creating VStack.
    Returns a VStack with the title already added.
    """
    stack = VStack(width=width, padding=PANE_PADDING, spacing=PANE_SPACING)
    stack.add(pane_title(title), height=24)
    return stack
