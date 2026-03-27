"""Design tokens — named constants for spacing, typography, and colors.

All UI code should use these tokens instead of magic numbers.
This ensures visual consistency and makes global changes trivial.
"""

from __future__ import annotations

from AppKit import NSColor, NSFont

# ── Spacing ──────────────────────────────────────────────────────────


class Spacing:
    """Named spacing values in points."""

    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24


# ── Typography ───────────────────────────────────────────────────────


class Font:
    """Named font sizes and constructors."""

    TITLE = 18.0
    HEADING = 14.0
    BODY = 13.0
    SECONDARY = 12.0
    SMALL = 11.0
    CAPTION = 10.0

    @staticmethod
    def title() -> NSFont:
        return NSFont.boldSystemFontOfSize_(Font.TITLE)

    @staticmethod
    def heading() -> NSFont:
        return NSFont.boldSystemFontOfSize_(Font.HEADING)

    @staticmethod
    def body(*, bold: bool = False) -> NSFont:
        return NSFont.boldSystemFontOfSize_(Font.BODY) if bold else NSFont.systemFontOfSize_(Font.BODY)

    @staticmethod
    def secondary() -> NSFont:
        return NSFont.systemFontOfSize_(Font.SECONDARY)

    @staticmethod
    def small() -> NSFont:
        return NSFont.systemFontOfSize_(Font.SMALL)

    @staticmethod
    def caption() -> NSFont:
        return NSFont.systemFontOfSize_(Font.CAPTION)


# ── Colors ───────────────────────────────────────────────────────────


class Colors:
    """Semantic color tokens. All return NSColor instances."""

    @staticmethod
    def primary() -> NSColor:
        return NSColor.labelColor()

    @staticmethod
    def secondary() -> NSColor:
        return NSColor.secondaryLabelColor()

    @staticmethod
    def tertiary() -> NSColor:
        return NSColor.tertiaryLabelColor()

    @staticmethod
    def danger() -> NSColor:
        return NSColor.systemRedColor()

    @staticmethod
    def accent() -> NSColor:
        return NSColor.controlAccentColor()

    @staticmethod
    def separator() -> NSColor:
        return NSColor.separatorColor()

    @staticmethod
    def card_background() -> NSColor:
        return NSColor.windowBackgroundColor().blendedColorWithFraction_ofColor_(0.06, NSColor.whiteColor())

    @staticmethod
    def card_border() -> NSColor:
        return NSColor.separatorColor().colorWithAlphaComponent_(0.3)
