"""DangerZone composite — destructive action card with red border.

Presentational only — receives action specs, never imports services.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from AppKit import NSBox, NSColor, NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.widgets.buttons import Size, button
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label


@dataclass(frozen=True)
class DangerAction:
    """Specification for a destructive action row."""

    label: str
    button_text: str
    on_click: Callable[[], None]


def build(*, actions: list[DangerAction], width: float = 0) -> NSView:
    """Build a danger zone card. Width is set by layout system if 0."""
    red = NSColor.systemRedColor()
    _pad = 16
    _header_h = 30
    _row_h = 38
    effective_w = width or 400

    total_h = _header_h + len(actions) * _row_h
    wrapper = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, effective_w, total_h))
    c = card(effective_w, total_h, border_color=red.colorWithAlphaComponent_(0.3))
    wrapper.addSubview_(c)
    content = c.contentView()

    header = label("Danger Zone", size=11.0, bold=True, color=red.colorWithAlphaComponent_(0.8))
    header.setFrame_(NSMakeRect(_pad, total_h - _pad - 14, 200, 14))
    content.addSubview_(header)

    sep = NSBox.alloc().initWithFrame_(NSMakeRect(_pad, total_h - _header_h, effective_w - _pad * 2, 1))
    sep.setBoxType_(2)
    content.addSubview_(sep)

    y = total_h - _header_h
    for action in actions:
        y -= _row_h
        row_label = label(action.label, size=12.0)
        row_label.setFrame_(NSMakeRect(_pad, y + 10, 300, 18))
        content.addSubview_(row_label)
        btn = button(action.button_text, target=None, action=None, size=Size(80, 22))
        btn.setFrame_(NSMakeRect(effective_w - _pad - 80, y + 8, 80, 22))
        content.addSubview_(btn)

    return wrapper
