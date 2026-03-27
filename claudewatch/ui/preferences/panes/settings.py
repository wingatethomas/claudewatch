"""Settings pane — feature toggles and danger zone."""

from __future__ import annotations

import objc
from AppKit import (
    NSBox,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSPopUpButton,
    NSSwitch,
    NSView,
)
from Foundation import NSMakeRect

from claudewatch.backend.core import features
from claudewatch.backend.core.features import FacetType
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, create_pane

_PAD = 24
_CARD_PAD = 16

_FEATURE_DETAILS: dict[str, str] = {
    "bookmarks": "Save sessions to resume later from the menu bar.",
    "notifications": "Get alerts when Claude needs your attention.",
    "background_summaries": "Periodically regenerate session summaries in the background.",
    "auto_updates": "Check GitHub for new releases periodically.",
    "launch_at_login": "Start ClaudeWatch automatically when you log in.",
}


def build_settings_pane(delegate: object, w: float, h: float) -> NSView:
    """Build the Settings pane with feature cards and danger zone."""
    view, content_top = create_pane("Settings", w, h)

    all_features = features.get_all()
    delegate._feature_controls = {}

    # Calculate scroll content height
    content_h = 0
    for feature in all_features:
        detail = _FEATURE_DETAILS.get(feature.key, "")
        toggle_h = 56 if detail else 44
        card_h = toggle_h + len(feature.facets) * 40
        content_h += card_h + 8
    content_h += 24  # gap before danger zone
    content_h += 30 + 2 * 38  # danger zone
    content_h += _PAD

    scroll_h = content_top
    inner_h = max(scroll_h, content_h)
    inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, inner_h))
    card_w = w - CONTENT_PADDING * 2

    y = inner_h

    # Feature cards
    for feature in all_features:
        card_h = _build_feature_card(inner, delegate, feature, _PAD, y, card_w)
        y -= card_h + 8

    # Danger zone
    y -= 16
    _build_danger_zone(inner, delegate, _PAD, y, card_w)

    if content_h <= scroll_h:
        inner.setFrame_(NSMakeRect(0, 0, w, scroll_h))
        view.addSubview_(inner)
    else:
        from AppKit import NSScrollView

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, w, scroll_h))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        scroll.setDocumentView_(inner)
        inner.scrollPoint_((0, inner_h))  # scroll to top
        view.addSubview_(scroll)

    return view


def _build_feature_card(  # noqa: PLR0912, PLR0913, PLR0915
    view: NSView,
    delegate: object,
    feature: features.Feature,
    x: float,
    y: float,
    card_w: float,
) -> float:
    """Build a feature card. Returns card height."""
    from claudewatch.ui.components.widgets.cards import card as make_card

    key = feature.key
    enabled = features.is_enabled(key)
    detail = _FEATURE_DETAILS.get(key, "")

    toggle_h = 56 if detail else 44
    facet_h = 40
    card_h = toggle_h + len(feature.facets) * facet_h

    c = make_card(card_w, card_h)
    c.setFrame_(NSMakeRect(x, y - card_h, card_w, card_h))
    view.addSubview_(c)
    content = c.contentView()

    # Toggle row
    row_y = card_h - toggle_h
    name_y = row_y + (toggle_h - 18) // 2 + (6 if detail else 0)
    name_lbl = label(feature.description, size=13.0)
    name_lbl.setFrame_(NSMakeRect(_CARD_PAD, name_y, card_w - _CARD_PAD * 2 - 60, 18))
    content.addSubview_(name_lbl)

    if detail:
        from AppKit import NSColor

        detail_lbl = secondary_label(detail, size=10.0)
        detail_lbl.setTextColor_(NSColor.tertiaryLabelColor())
        detail_lbl.setFrame_(NSMakeRect(_CARD_PAD, name_y - 16, card_w - _CARD_PAD * 2 - 60, 14))
        content.addSubview_(detail_lbl)

    sw = NSSwitch.alloc().initWithFrame_(NSMakeRect(card_w - _CARD_PAD - 46, row_y + (toggle_h - 22) // 2, 46, 22))
    sw.setState_(NSControlStateValueOn if enabled else NSControlStateValueOff)
    sw.setRepresentedObject_(key)
    sw.setTarget_(delegate)
    sw.setAction_(objc.selector(delegate.featureToggled_, signature=b"v@:@"))
    content.addSubview_(sw)

    # Facet rows
    facet_controls: list[object] = []
    for i, facet in enumerate(feature.facets):
        fy = row_y - (i + 1) * facet_h
        sep = NSBox.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, fy + facet_h - 1, card_w - _CARD_PAD * 2, 1))
        sep.setBoxType_(2)
        content.addSubview_(sep)

        facet_label_text = facet.description or facet.name.replace("_", " ").title()
        from AppKit import NSColor

        flbl = label(facet_label_text, size=12.0, color=NSColor.secondaryLabelColor())
        flbl.setFrame_(NSMakeRect(_CARD_PAD, fy + 11, 140, 18))
        content.addSubview_(flbl)

        if facet.type == FacetType.CHOICE:
            popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(card_w - _CARD_PAD - 160, fy + 8, 160, 24), False
            )
            popup.setFont_(NSFont.systemFontOfSize_(12.0))
            popup.addItemsWithTitles_(list(facet.options))
            current = features.get_facet(key, facet.name)
            if current is not None:
                popup.selectItemWithTitle_(str(current))
            popup.cell().setRepresentedObject_(f"{key}|{facet.name}")
            popup.setTarget_(delegate)
            popup.setAction_(objc.selector(delegate.facetChanged_, signature=b"v@:@"))
            popup.setEnabled_(enabled)
            content.addSubview_(popup)
            facet_controls.append(popup)
        elif facet.type == FacetType.BOOL:
            fsw = NSSwitch.alloc().initWithFrame_(NSMakeRect(card_w - _CARD_PAD - 46, fy + 9, 46, 22))
            val = features.get_facet(key, facet.name)
            fsw.setState_(NSControlStateValueOn if val else NSControlStateValueOff)
            fsw.cell().setRepresentedObject_(f"{key}|{facet.name}")
            fsw.setTarget_(delegate)
            fsw.setAction_(objc.selector(delegate.facetBoolChanged_, signature=b"v@:@"))
            fsw.setEnabled_(enabled)
            content.addSubview_(fsw)
            facet_controls.append(fsw)

    delegate._feature_controls[key] = facet_controls
    return card_h


def _build_danger_zone(view: NSView, delegate: object, x: float, y: float, card_w: float) -> None:
    """Build the danger zone card."""
    from AppKit import NSColor

    from claudewatch.ui.components.widgets.buttons import Size, button
    from claudewatch.ui.components.widgets.cards import card as make_card

    red = NSColor.systemRedColor()
    header_h = 30
    row_h = 38
    total_h = header_h + 2 * row_h

    c = make_card(card_w, total_h, border_color=red.colorWithAlphaComponent_(0.3))
    c.setFrame_(NSMakeRect(x, y - total_h, card_w, total_h))
    view.addSubview_(c)
    dc = c.contentView()

    # Header
    header = label("Danger Zone", size=11.0, bold=True, color=red.colorWithAlphaComponent_(0.8))
    header.setFrame_(NSMakeRect(_CARD_PAD, total_h - _CARD_PAD - 14, 200, 14))
    dc.addSubview_(header)

    sep = NSBox.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, total_h - header_h, card_w - _CARD_PAD * 2, 1))
    sep.setBoxType_(2)
    dc.addSubview_(sep)

    # Row 1: Clear bookmarks
    r1y = total_h - header_h - row_h
    r1_label = label("Clear all bookmarks", size=12.0)
    r1_label.setFrame_(NSMakeRect(_CARD_PAD, r1y + 10, card_w - _CARD_PAD * 2 - 88, 18))
    dc.addSubview_(r1_label)
    bm_btn = button(
        "Clear...",
        target=delegate,
        action=objc.selector(delegate.clearBookmarks_, signature=b"v@:@"),
        size=Size(80, 22),
    )
    bm_btn.setFrame_(NSMakeRect(card_w - _CARD_PAD - 80, r1y + 8, 80, 22))
    dc.addSubview_(bm_btn)

    # Separator
    sep2 = NSBox.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, r1y, card_w - _CARD_PAD * 2, 1))
    sep2.setBoxType_(2)
    dc.addSubview_(sep2)

    # Row 2: Clear summaries
    r2y = r1y - row_h
    r2_label = label("Clear all summaries", size=12.0)
    r2_label.setFrame_(NSMakeRect(_CARD_PAD, r2y + 10, card_w - _CARD_PAD * 2 - 88, 18))
    dc.addSubview_(r2_label)
    sum_btn = button(
        "Clear...",
        target=delegate,
        action=objc.selector(delegate.clearSummaries_, signature=b"v@:@"),
        size=Size(80, 22),
    )
    sum_btn.setFrame_(NSMakeRect(card_w - _CARD_PAD - 80, r2y + 8, 80, 22))
    dc.addSubview_(sum_btn)
