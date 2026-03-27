"""Card factories — grouped container components."""

from __future__ import annotations

from AppKit import NSBox, NSColor
from Foundation import NSMakeRect

_CARD_RADIUS = 10.0


def card(
    width: float,
    height: float,
    *,
    border_color: NSColor | None = None,
) -> NSBox:
    """Rounded-rect grouped container like macOS Settings cards."""
    from claudewatch.ui.theme import theme  # noqa: PLC0415

    box = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    box.setBoxType_(4)
    box.setBorderType_(1)
    box.setCornerRadius_(_CARD_RADIUS)
    box.setFillColor_(theme.card_background)
    box.setBorderColor_(border_color or theme.card_border)
    box.setTitlePosition_(0)
    box.setContentViewMargins_((0, 0))
    return box
