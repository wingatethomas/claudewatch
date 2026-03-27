"""Label factories — text display components."""

from __future__ import annotations

from AppKit import NSColor, NSFont, NSTextField
from Foundation import NSMakeRect


def label(
    text: str,
    *,
    size: float = 13.0,
    bold: bool = False,
    color: NSColor | None = None,
) -> NSTextField:
    """Create a text label. Frame starts at zero — set by the layout system or caller."""
    lbl = NSTextField.labelWithString_(text)
    lbl.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    lbl.setFrame_(NSMakeRect(0, 0, 0, 0))  # zero frame — layout system or caller sets actual size
    if color:
        lbl.setTextColor_(color)
    return lbl


def secondary_label(text: str, *, size: float = 12.0) -> NSTextField:
    """Label with secondary (dimmed) color."""
    return label(text, size=size, color=NSColor.secondaryLabelColor())


def section_header(text: str) -> NSTextField:
    """Uppercase section header (e.g. 'WHAT'S NEW')."""
    return label(text, size=10.0, color=NSColor.tertiaryLabelColor())


def pane_title(text: str) -> NSTextField:
    """Large bold pane header (e.g. 'Settings')."""
    return label(text, size=18.0, bold=True)
