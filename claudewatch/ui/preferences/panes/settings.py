"""Settings pane — feature toggles, test actions, and danger zone."""

from __future__ import annotations

import objc
from AppKit import (
    NSBox,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSPopUpButton,
    NSScrollView,
    NSSwitch,
    NSView,
)
from Foundation import NSMakeRect

from claudewatch.backend.core import features
from claudewatch.backend.core.features import FacetType
from claudewatch.ui.components.tokens import Font, Spacing, get_scheme
from claudewatch.ui.components.widgets.buttons import Size, button
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane
from claudewatch.ui.theme import theme

_FEATURE_DETAILS: dict[str, str] = {
    "bookmarks": "Save sessions to resume later from the menu bar.",
    "notifications": "Get alerts when Claude needs your attention.",
    "background_summaries": "Periodically regenerate session summaries in the background.",
    "auto_updates": "Check GitHub for new releases periodically.",
    "launch_at_login": "Start ClaudeWatch automatically when you log in.",
    "accessibility": "Color scheme for status dots in the menu bar.",
}


class SettingsPane(BasePane):
    """Settings pane with feature cards, test actions, and danger zone."""

    @property
    def title(self) -> str:
        return "Settings"

    @property
    def subtitle(self) -> str:
        return "Feature toggles and preferences"

    def build_content(self, view: NSView, content_top: float) -> None:  # noqa: PLR0915
        all_features = features.get_all()
        self.delegate._feature_controls = {}

        # Calculate scroll content height
        content_h = 0
        for feature in all_features:
            detail = _FEATURE_DETAILS.get(feature.key, "")
            toggle_row_h = 56 if detail else 44
            feature_card_h = toggle_row_h + len(feature.facets) * 40
            content_h += feature_card_h + Spacing.SM
        content_h += Spacing.XL  # gap before danger zone
        content_h += 36 + 2 * 38  # danger zone
        content_h += Spacing.XL

        scroll_h = content_top
        inner_h = max(scroll_h, content_h)
        inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self.width, inner_h))

        y = inner_h

        # Feature cards
        for feature in all_features:
            feature_card_h = _build_feature_card(inner, self.delegate, feature, CONTENT_PADDING, y, self.card_width)
            y -= feature_card_h + Spacing.SM

        # Danger zone
        y -= Spacing.LG
        _build_danger_zone(inner, self.delegate, CONTENT_PADDING, y, self.card_width)

        if content_h <= scroll_h:
            inner.setFrame_(NSMakeRect(0, 0, self.width, scroll_h))
            view.addSubview_(inner)
        else:
            scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, self.width, scroll_h))
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            scroll.setDrawsBackground_(False)
            scroll.setDocumentView_(inner)
            inner.scrollPoint_((0, inner_h))
            view.addSubview_(scroll)


# Legacy function interface for window.py
def build_settings_pane(delegate: object, w: float, h: float) -> NSView:
    """Build the Settings pane."""
    return SettingsPane(delegate, w, h).build()


def _build_feature_card(  # noqa: PLR0912, PLR0913, PLR0915
    view: NSView,
    delegate: object,
    feature: features.Feature,
    x: float,
    y: float,
    card_w: float,
) -> float:
    """Build a feature card. Returns card height."""
    key = feature.key
    enabled = features.is_enabled(key)
    detail = _FEATURE_DETAILS.get(key, "")

    toggle_row_h = 56 if detail else 44
    facet_row_h = 40
    feature_card_h = toggle_row_h + len(feature.facets) * facet_row_h

    feature_card = card(card_w, feature_card_h)
    feature_card.setFrame_(NSMakeRect(x, y - feature_card_h, card_w, feature_card_h))
    view.addSubview_(feature_card)
    content = feature_card.contentView()

    # Toggle row
    row_y = feature_card_h - toggle_row_h
    name_y = row_y + (toggle_row_h - 18) // 2 + (6 if detail else 0)
    name_label = label(feature.description, size=Font.BODY)
    name_label.setFrame_(NSMakeRect(Spacing.LG, name_y, card_w - Spacing.LG * 2 - 60, 18))
    content.addSubview_(name_label)

    if detail:
        detail_label = secondary_label(detail, size=Font.CAPTION)
        detail_label.setTextColor_(theme.tertiary)
        detail_label.setFrame_(NSMakeRect(Spacing.LG, name_y - 16, card_w - Spacing.LG * 2 - 60, 14))
        content.addSubview_(detail_label)

    toggle_switch = NSSwitch.alloc().initWithFrame_(
        NSMakeRect(card_w - Spacing.LG - 46, row_y + (toggle_row_h - 22) // 2, 46, 22)
    )
    toggle_switch.setState_(NSControlStateValueOn if enabled else NSControlStateValueOff)
    toggle_switch.setRepresentedObject_(key)
    toggle_switch.setTarget_(delegate)
    toggle_switch.setAction_(objc.selector(delegate.featureToggled_, signature=b"v@:@"))
    content.addSubview_(toggle_switch)

    # Facet rows
    facet_controls: list[object] = []
    for i, facet in enumerate(feature.facets):
        facet_y = row_y - (i + 1) * facet_row_h
        separator = NSBox.alloc().initWithFrame_(
            NSMakeRect(Spacing.LG, facet_y + facet_row_h - 1, card_w - Spacing.LG * 2, 1)
        )
        separator.setBoxType_(2)
        content.addSubview_(separator)

        facet_text = facet.description or facet.name.replace("_", " ").title()
        facet_label = label(facet_text, size=Font.SECONDARY, color=theme.secondary)
        facet_label.setFrame_(NSMakeRect(Spacing.LG, facet_y + 11, 140, 18))
        content.addSubview_(facet_label)

        if facet.type == FacetType.CHOICE:
            facet_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(card_w - Spacing.LG - 160, facet_y + 8, 160, 24), False
            )
            facet_popup.setFont_(NSFont.systemFontOfSize_(Font.SECONDARY))
            facet_popup.addItemsWithTitles_(list(facet.options))
            current = features.get_facet(key, facet.name)
            if current is not None:
                display_value = str(current)
                # Normalize legacy values to current option names
                if key == "accessibility" and facet.name == "color_scheme":
                    display_value = get_scheme(display_value).name
                facet_popup.selectItemWithTitle_(display_value)
            facet_popup.cell().setRepresentedObject_(f"{key}|{facet.name}")
            facet_popup.setTarget_(delegate)
            facet_popup.setAction_(objc.selector(delegate.facetChanged_, signature=b"v@:@"))
            facet_popup.setEnabled_(enabled)
            content.addSubview_(facet_popup)
            facet_controls.append(facet_popup)
        elif facet.type == FacetType.BOOL:
            facet_switch = NSSwitch.alloc().initWithFrame_(NSMakeRect(card_w - Spacing.LG - 46, facet_y + 9, 46, 22))
            val = features.get_facet(key, facet.name)
            facet_switch.setState_(NSControlStateValueOn if val else NSControlStateValueOff)
            facet_switch.cell().setRepresentedObject_(f"{key}|{facet.name}")
            facet_switch.setTarget_(delegate)
            facet_switch.setAction_(objc.selector(delegate.facetBoolChanged_, signature=b"v@:@"))
            facet_switch.setEnabled_(enabled)
            content.addSubview_(facet_switch)
            facet_controls.append(facet_switch)

    delegate._feature_controls[key] = facet_controls
    return feature_card_h


def _build_danger_zone(view: NSView, delegate: object, x: float, y: float, card_w: float) -> None:
    """Build the danger zone card."""
    danger_color = theme.danger
    header_h = 36
    row_h = 38
    total_h = header_h + 2 * row_h

    danger_card = card(card_w, total_h, border_color=danger_color.colorWithAlphaComponent_(0.3))
    danger_card.setFrame_(NSMakeRect(x, y - total_h, card_w, total_h))
    view.addSubview_(danger_card)
    content = danger_card.contentView()

    # Header
    header_label = label("Danger Zone", size=Font.SMALL, bold=True, color=danger_color.colorWithAlphaComponent_(0.8))
    header_label.setFrame_(NSMakeRect(Spacing.LG, total_h - 10 - 14, 200, 14))
    content.addSubview_(header_label)

    header_separator = NSBox.alloc().initWithFrame_(
        NSMakeRect(Spacing.LG, total_h - header_h, card_w - Spacing.LG * 2, 1)
    )
    header_separator.setBoxType_(2)
    content.addSubview_(header_separator)

    # Row 1: Clear bookmarks
    bookmarks_row_y = total_h - header_h - row_h
    bookmarks_label = label("Clear all bookmarks", size=Font.SECONDARY)
    bookmarks_label.setFrame_(NSMakeRect(Spacing.LG, bookmarks_row_y + 10, card_w - Spacing.LG * 2 - 88, 18))
    content.addSubview_(bookmarks_label)
    bookmarks_button = button(
        "Clear...",
        target=delegate,
        action=objc.selector(delegate.clearBookmarks_, signature=b"v@:@"),
        size=Size(80, 22),
    )
    bookmarks_button.setFrame_(NSMakeRect(card_w - Spacing.LG - 80, bookmarks_row_y + 8, 80, 22))
    content.addSubview_(bookmarks_button)

    # Separator
    row_separator = NSBox.alloc().initWithFrame_(NSMakeRect(Spacing.LG, bookmarks_row_y, card_w - Spacing.LG * 2, 1))
    row_separator.setBoxType_(2)
    content.addSubview_(row_separator)

    # Row 2: Clear summaries
    summaries_row_y = bookmarks_row_y - row_h
    summaries_label = label("Clear all summaries", size=Font.SECONDARY)
    summaries_label.setFrame_(NSMakeRect(Spacing.LG, summaries_row_y + 10, card_w - Spacing.LG * 2 - 88, 18))
    content.addSubview_(summaries_label)
    summaries_button = button(
        "Clear...",
        target=delegate,
        action=objc.selector(delegate.clearSummaries_, signature=b"v@:@"),
        size=Size(80, 22),
    )
    summaries_button.setFrame_(NSMakeRect(card_w - Spacing.LG - 80, summaries_row_y + 8, 80, 22))
    content.addSubview_(summaries_button)
