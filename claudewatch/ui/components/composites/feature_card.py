"""FeatureCard composite — toggle card for a single feature.

Presentational only — receives data + callbacks, never imports services.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from AppKit import NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.widgets.buttons import popup, toggle
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, secondary_label

# Module-level reference store to prevent GC of callback targets
_callback_refs: list[object] = []


@dataclass(frozen=True)
class FacetSpec:
    """Specification for a configurable facet within a feature card."""

    label: str
    value: str
    choices: tuple[str, ...] = ()


def build(  # noqa: PLR0913
    *,
    title: str,
    description: str,
    enabled: bool,
    on_toggle: Callable[[bool], None],  # noqa: ARG001 — wired by container via toggle target
    facets: list[FacetSpec] | None = None,
    on_facet_change: Callable[[str, str], None] | None = None,
) -> NSView:
    """Build a feature toggle card. Pure presentational."""
    _pad = 16
    _row_h = 44
    _desc_extra = 12
    _facet_h = 36

    has_desc = bool(description)
    main_h = _row_h + (_desc_extra if has_desc else 0)
    facet_count = len(facets) if facets else 0
    total_h = main_h + facet_count * _facet_h

    # Wrapper view holds card + keeps Python references alive
    wrapper = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 0, total_h))
    c = card(0, total_h)
    c.setFrame_(NSMakeRect(0, 0, 0, total_h))
    wrapper.addSubview_(c)
    content = c.contentView()

    # Title label
    title_lbl = label(title, size=13.0, bold=True)
    title_lbl.setFrame_(NSMakeRect(_pad, total_h - _pad - 18, 300, 18))
    content.addSubview_(title_lbl)

    # Toggle switch
    sw = toggle(enabled=enabled, target=None, action=None)
    sw.setFrame_(NSMakeRect(0, total_h - _pad - 18, 46, 22))
    content.addSubview_(sw)

    if has_desc:
        desc_lbl = secondary_label(description, size=11.0)
        desc_lbl.setFrame_(NSMakeRect(_pad, total_h - _pad - 18 - 16, 300, 14))
        content.addSubview_(desc_lbl)

    # Facet rows
    if facets and on_facet_change:
        y = total_h - main_h
        for facet in facets:
            y -= _facet_h
            facet_lbl = label(facet.label, size=12.0)
            facet_lbl.setFrame_(NSMakeRect(_pad, y + 8, 140, 18))
            content.addSubview_(facet_lbl)

            if facet.choices:
                p = popup(
                    list(facet.choices),
                    selected=facet.value,
                    target=None,
                    action=None,
                    width=140,
                )
                p.setFrame_(NSMakeRect(160, y + 4, 140, 24))
                content.addSubview_(p)

    return wrapper
