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


# ── Status Color Schemes ─────────────────────────────────────────────


def _rgb(r: float, g: float, b: float) -> NSColor:
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)


class StatusScheme:
    """A set of three colors for session status dots."""

    def __init__(self, name: str, attention: NSColor, working: NSColor, idle: NSColor) -> None:
        self.name = name
        self.attention = attention
        self.working = working
        self.idle = idle


STATUS_SCHEMES: dict[str, StatusScheme] = {
    "default": StatusScheme(
        "Default",
        attention=_rgb(0.85, 0.30, 0.28),
        working=_rgb(0.25, 0.65, 0.30),
        idle=_rgb(0.85, 0.65, 0.15),
    ),
    "deuteranopia": StatusScheme(
        "Deuteranopia (red-green)",
        attention=_rgb(0.90, 0.40, 0.10),
        working=_rgb(0.20, 0.50, 0.85),
        idle=_rgb(0.70, 0.70, 0.70),
    ),
    "protanopia": StatusScheme(
        "Protanopia (red-green)",
        attention=_rgb(0.90, 0.60, 0.00),
        working=_rgb(0.00, 0.45, 0.85),
        idle=_rgb(0.60, 0.60, 0.60),
    ),
    "high_contrast": StatusScheme(
        "High Contrast",
        attention=_rgb(1.00, 0.20, 0.20),
        working=_rgb(0.20, 0.80, 1.00),
        idle=_rgb(1.00, 1.00, 0.30),
    ),
}


def get_scheme(name: str) -> StatusScheme:
    """Look up a scheme by name. Returns default if not found."""
    return STATUS_SCHEMES.get(name, STATUS_SCHEMES["default"])
