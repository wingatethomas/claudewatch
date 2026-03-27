"""Card factories — grouped container components."""

from __future__ import annotations

from AppKit import NSBox, NSColor
from Foundation import NSMakeRect

from claudewatch.ui.components.tokens import Colors

_CARD_RADIUS = 10.0


def card(
    width: float,
    height: float,
    *,
    border_color: NSColor | None = None,
) -> NSBox:
    """Rounded-rect grouped container like macOS Settings cards."""
    box = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    box.setBoxType_(4)
    box.setBorderType_(1)
    box.setCornerRadius_(_CARD_RADIUS)
    box.setFillColor_(Colors.card_background())
    box.setBorderColor_(border_color or Colors.card_border())
    box.setTitlePosition_(0)
    box.setContentViewMargins_((0, 0))
    return box
