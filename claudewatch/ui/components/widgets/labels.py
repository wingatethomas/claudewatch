"""Label factories — text display components."""

from __future__ import annotations

from AppKit import NSColor, NSFont, NSTextField
from Foundation import NSMakeRect

from claudewatch.ui.components.tokens import Font


def label(
    text: str,
    *,
    size: float = Font.BODY,
    bold: bool = False,
    color: NSColor | None = None,
) -> NSTextField:
    """Create a text label. Frame starts at zero — set by the layout system or caller."""
    lbl = NSTextField.labelWithString_(text)
    lbl.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    lbl.setFrame_(NSMakeRect(0, 0, 0, 0))
    if color:
        lbl.setTextColor_(color)
    return lbl


def secondary_label(text: str, *, size: float = Font.SECONDARY) -> NSTextField:
    """Label with secondary (dimmed) color."""
    from claudewatch.ui.theme import theme  # noqa: PLC0415

    return label(text, size=size, color=theme.secondary)


def section_header(text: str) -> NSTextField:
    """Uppercase section header."""
    from claudewatch.ui.theme import theme  # noqa: PLC0415

    return label(text, size=Font.CAPTION, color=theme.tertiary)


def pane_title(text: str) -> NSTextField:
    """Large bold pane header."""
    return label(text, size=Font.TITLE, bold=True)
