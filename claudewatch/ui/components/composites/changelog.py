"""ChangelogView composite — renders release notes from GitHub.

Presentational only — receives parsed release data, never fetches.
"""

from __future__ import annotations

from AppKit import NSScrollView, NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.widgets.labels import label, secondary_label


def build_changelog(*, releases: list[tuple[str, list[str]]], width: float, height: float) -> NSView:
    """Build a scrollable changelog view from release data."""
    _ver_h = 18
    _bullet_h = 14
    _ver_gap = 8
    _pad = 10

    if not releases:
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        empty = secondary_label("No releases found", size=11.0)
        empty.setFrame_(NSMakeRect(_pad, height // 2, width - _pad * 2, 18))
        container.addSubview_(empty)
        return container

    content_h = _pad
    for _tag, items in releases:
        content_h += _ver_h + len(items) * _bullet_h + _ver_gap
    content_h += _pad

    inner_h = max(height, content_h)
    inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, inner_h))
    cy = inner_h - _pad

    for tag, items in releases:
        cy -= _ver_h
        ver = label(tag, size=11.0, bold=True)
        ver.setFrame_(NSMakeRect(_pad, cy, 200, _ver_h))
        inner.addSubview_(ver)
        for item in items:
            cy -= _bullet_h
            bullet = secondary_label(f"• {item}", size=10.0)
            bullet.setFrame_(NSMakeRect(_pad + 8, cy, width - _pad * 2 - 20, _bullet_h))
            inner.addSubview_(bullet)
        cy -= _ver_gap

    if content_h <= height:
        inner.setFrame_(NSMakeRect(0, 0, width, height))
        return inner

    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    scroll.setHasVerticalScroller_(True)
    scroll.setAutohidesScrollers_(True)
    scroll.setDrawsBackground_(False)
    scroll.setDocumentView_(inner)
    return scroll
