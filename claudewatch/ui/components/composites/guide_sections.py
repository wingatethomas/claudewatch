"""GuideSections composite — renders static guide content.

Presentational only — receives section data, renders scrollable view.
"""

from __future__ import annotations

from AppKit import NSScrollView, NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.widgets.labels import label, secondary_label


def build(*, sections: list[tuple[str, list[str]]], width: float, height: float) -> NSView:
    """Build a scrollable guide view from section data."""
    _section_h = 18
    _bullet_h = 16
    _section_gap = 16
    _pad = 12

    if not sections:
        return NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))

    content_h = _pad
    for _title, items in sections:
        content_h += _section_h + len(items) * _bullet_h + _section_gap
    content_h += _pad

    inner_h = max(height, content_h)
    inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, inner_h))
    cy = inner_h - _pad

    for title, items in sections:
        cy -= _section_h
        lbl = label(title, size=12.0, bold=True)
        lbl.setFrame_(NSMakeRect(_pad, cy, width - _pad * 2, _section_h))
        inner.addSubview_(lbl)
        for item in items:
            cy -= _bullet_h
            bullet = secondary_label(f"• {item}", size=10.5)
            bullet.setFrame_(NSMakeRect(_pad + 10, cy, width - _pad * 2 - 20, _bullet_h))
            inner.addSubview_(bullet)
        cy -= _section_gap

    if content_h <= height:
        inner.setFrame_(NSMakeRect(0, 0, width, height))
        return inner

    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    scroll.setHasVerticalScroller_(True)
    scroll.setAutohidesScrollers_(True)
    scroll.setDrawsBackground_(False)
    scroll.setDocumentView_(inner)
    return scroll
