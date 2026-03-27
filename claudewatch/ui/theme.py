"""Theme — bridge between design tokens and app settings.

Reads the user's accessibility preferences and provides the active color scheme.
All UI code that needs status colors should import from here, not from tokens directly.

    from claudewatch.ui.theme import get_status_color, get_status_colors

This module depends on both tokens (design system) and features (business logic),
keeping that dependency out of the pure design system layer.
"""

from __future__ import annotations

from AppKit import NSColor

from claudewatch.backend.core import features
from claudewatch.backend.core.models import SessionStatus
from claudewatch.ui.components.tokens import StatusScheme, get_scheme


def get_active_scheme() -> StatusScheme:
    """Get the user's configured color scheme."""
    scheme_name = str(features.get_facet("accessibility", "color_scheme") or "default")
    return get_scheme(scheme_name)


def get_status_colors() -> dict[SessionStatus, NSColor]:
    """Get a dict mapping session status to colors from the active scheme."""
    scheme = get_active_scheme()
    return {
        SessionStatus.ATTENTION: scheme.attention,
        SessionStatus.WORKING: scheme.working,
        SessionStatus.IDLE: scheme.idle,
    }


def get_status_color(status: SessionStatus) -> NSColor:
    """Get the color for a single session status."""
    return get_status_colors().get(status, NSColor.secondaryLabelColor())
