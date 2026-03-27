"""Status icon rendering for the menu bar."""

from __future__ import annotations

from AppKit import (
    NSBezierPath,
    NSColor,
    NSFont,
    NSImage,
    NSMutableAttributedString,
    NSString,
    NSWorkspace,
)
from Foundation import NSMakeRect, NSMakeSize, NSRange

from claudewatch.backend.core.models import (
    HOST_APP_PATH,
    ClaudeSession,
    HostApp,
    SessionStatus,
)


# Status colors — the Digital Color Meter samples were display-rendered values,
# not sRGB input. Use brighter sRGB values that render to match Claude Code on screen.
def get_status_colors() -> dict:
    """Get status colors from the active color scheme."""
    from claudewatch.ui.components.tokens import get_active_scheme  # noqa: PLC0415 — circular dep

    scheme = get_active_scheme()
    return {
        SessionStatus.ATTENTION: scheme.attention,
        SessionStatus.WORKING: scheme.working,
        SessionStatus.IDLE: scheme.idle,
    }


# Cache for scaled NSImage icons
_app_icon_cache: dict[HostApp, NSImage | None] = {}


def make_header_title(text: str, status: SessionStatus, count: int) -> NSMutableAttributedString:
    """Create an attributed string like '⚠ Needs Attention (3)  •••' with small colored dots."""
    dots = "●" * count
    full = f"{text} ({count})  {dots}"
    attr_str = NSMutableAttributedString.alloc().initWithString_(full)
    # Style the dots: colored, smaller font, baseline-shifted up to center vertically
    dot_start = len(full) - len(dots)
    dot_range = NSRange(dot_start, len(dots))
    color = get_status_colors().get(status, NSColor.secondaryLabelColor())
    attr_str.addAttribute_value_range_("NSColor", color, dot_range)
    attr_str.addAttribute_value_range_("NSFont", NSFont.systemFontOfSize_(7.0), dot_range)
    attr_str.addAttribute_value_range_("NSBaselineOffset", 2.0, dot_range)
    return attr_str


def render_dot_row(status: SessionStatus, count: int) -> NSImage:
    """Render a row of colored dots as an NSImage for section headers."""
    _dot_diameter = 6.0
    _dot_gap = 3.0
    _dot_step = _dot_diameter + _dot_gap
    _height = 12.0

    width = max(count * _dot_step - _dot_gap, 1)
    img = NSImage.alloc().initWithSize_(NSMakeSize(width, _height))
    img.lockFocus()
    try:
        color = get_status_colors().get(status, NSColor.secondaryLabelColor())
        color.set()
        center_y = (_height - _dot_diameter) / 2.0
        for i in range(count):
            x = i * _dot_step
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(x, center_y, _dot_diameter, _dot_diameter),
            ).fill()
    finally:
        img.unlockFocus()
    img.setTemplate_(False)
    return img


def render_status_icon(  # noqa: PLR0914
    attention: list[ClaudeSession],
    working: list[ClaudeSession],
    idle: list[ClaudeSession],
) -> NSImage:
    """Render a menu bar icon: ✦ symbol + colored dots (max 12, 2 rows of 4+)."""
    _dot_radius = 2.0
    _dot_gap = 2.0
    _dot_step = _dot_radius * 2 + _dot_gap
    _dots_per_row = 4
    _row_height = 7.0
    _symbol_width = 18.0
    _icon_height = 18.0
    _max_dots = 12

    # Build dot list: attention first (red), then working (green), then idle (yellow)
    dots: list[NSColor] = []
    for _ in attention:
        dots.append(get_status_colors()[SessionStatus.ATTENTION])
    for _ in working:
        dots.append(get_status_colors()[SessionStatus.WORKING])
    for _ in idle:
        dots.append(get_status_colors()[SessionStatus.IDLE])
    dots = dots[:_max_dots]

    n_dots = len(dots)
    two_rows = n_dots > _dots_per_row
    cols = min(n_dots, _dots_per_row)
    dots_width = cols * _dot_step - _dot_gap if cols else 0
    width = _symbol_width + dots_width + 2.0

    img = NSImage.alloc().initWithSize_(NSMakeSize(width, _icon_height))
    img.lockFocus()
    try:
        # Draw ✦ symbol
        attrs = {
            "NSFont": NSFont.systemFontOfSize_(15.0),
            "NSColor": NSColor.labelColor(),
        }
        symbol = NSString.stringWithString_("✦")
        symbol.drawAtPoint_withAttributes_((0.0, 0.0), attrs)

        # Draw dots in a grid — 1 or 2 rows
        if two_rows:
            top_y = _icon_height / 2.0 + 1.0
            bot_y = top_y - _row_height
        else:
            top_y = _icon_height / 2.0 - _dot_radius + 1.0
            bot_y = top_y  # unused

        for i, color in enumerate(dots):
            col = i % _dots_per_row
            row_y = top_y if i < _dots_per_row else bot_y
            x = _symbol_width + col * _dot_step
            color.set()
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(x, row_y, _dot_radius * 2, _dot_radius * 2),
            ).fill()
    finally:
        img.unlockFocus()
    img.setTemplate_(False)
    return img


def get_app_icon(app: HostApp, size: int = 16) -> NSImage | None:
    """Get the actual macOS app icon, scaled to menu size. Cached."""
    if app in _app_icon_cache:
        return _app_icon_cache[app]
    path = HOST_APP_PATH.get(app)
    if not path:
        _app_icon_cache[app] = None
        return None
    icon = NSWorkspace.sharedWorkspace().iconForFile_(path)
    if icon:
        icon = icon.copy()
        icon.setSize_((size, size))
    _app_icon_cache[app] = icon
    return icon


def sf_icon(name: str, size: float = 14.0) -> NSImage | None:
    """Load an SF Symbol as an NSImage for menu items."""
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if img:
        img = img.copy()
        img.setSize_((size, size))
    return img
