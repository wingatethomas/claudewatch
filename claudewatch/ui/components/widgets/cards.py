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
    box = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    box.setBoxType_(4)  # NSBoxCustom
    box.setBorderType_(1)  # NSLineBorder
    box.setCornerRadius_(_CARD_RADIUS)
    box.setFillColor_(NSColor.windowBackgroundColor().blendedColorWithFraction_ofColor_(0.06, NSColor.whiteColor()))
    box.setBorderColor_(border_color or NSColor.separatorColor().colorWithAlphaComponent_(0.3))
    box.setTitlePosition_(0)  # NSNoTitle
    box.setContentViewMargins_((0, 0))
    return box
