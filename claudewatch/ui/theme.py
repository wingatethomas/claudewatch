"""Theme — single source of truth for all UI colors and styles.

All UI code should import colors from here, not from AppKit or tokens directly.

    from claudewatch.ui.theme import theme

    label.setTextColor_(theme.secondary)
    card.setBorderColor_(theme.card_border)
    color = theme.status_color(SessionStatus.ATTENTION)

This module bridges the design system (tokens) with app settings (features),
keeping both layers free of cross-dependencies.
"""

from __future__ import annotations

from AppKit import NSColor, NSFont

from claudewatch.backend.core import features
from claudewatch.backend.core.models import SessionStatus
from claudewatch.ui.components.tokens import Colors, Font, StatusScheme, get_scheme


class Theme:
    """Active theme — reads user settings, provides all UI colors and fonts.

    Instantiated once as module-level `theme`. All properties read live settings
    so changes take effect on the next render cycle.
    """

    # ── Status colors (from accessibility scheme) ──

    @property
    def scheme(self) -> StatusScheme:
        scheme_name = str(features.get_facet("accessibility", "color_scheme") or "Default")
        return get_scheme(scheme_name)

    def status_color(self, status: SessionStatus) -> NSColor:
        """Get color for a session status."""
        mapping = {
            SessionStatus.ATTENTION: self.scheme.attention,
            SessionStatus.WORKING: self.scheme.working,
            SessionStatus.IDLE: self.scheme.idle,
        }
        return mapping.get(status, self.secondary)

    # ── Semantic colors (from system, adapt to light/dark mode) ──

    @property
    def primary(self) -> NSColor:
        return Colors.primary()

    @property
    def secondary(self) -> NSColor:
        return Colors.secondary()

    @property
    def tertiary(self) -> NSColor:
        return Colors.tertiary()

    @property
    def danger(self) -> NSColor:
        return Colors.danger()

    @property
    def accent(self) -> NSColor:
        return Colors.accent()

    @property
    def separator(self) -> NSColor:
        return Colors.separator()

    @property
    def card_background(self) -> NSColor:
        return Colors.card_background()

    @property
    def card_border(self) -> NSColor:
        return Colors.card_border()

    # ── Fonts ──

    @property
    def title_font(self) -> NSFont:
        return Font.title()

    @property
    def heading_font(self) -> NSFont:
        return Font.heading()

    @property
    def body_font(self) -> NSFont:
        return Font.body()

    @property
    def secondary_font(self) -> NSFont:
        return Font.secondary()

    @property
    def small_font(self) -> NSFont:
        return Font.small()

    @property
    def caption_font(self) -> NSFont:
        return Font.caption()


# Singleton — import this everywhere
theme = Theme()


# ── Convenience functions for backward compat ──


def get_status_colors() -> dict[SessionStatus, NSColor]:
    """Get a dict mapping session status to colors from the active scheme."""
    return {
        SessionStatus.ATTENTION: theme.scheme.attention,
        SessionStatus.WORKING: theme.scheme.working,
        SessionStatus.IDLE: theme.scheme.idle,
    }


def get_status_color(status: SessionStatus) -> NSColor:
    """Get the color for a single session status."""
    return theme.status_color(status)
