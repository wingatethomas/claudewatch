"""Deprecated — use claudewatch.ui.menu.core instead.

This file re-exports for backward compat. Will be removed in a future release.
"""

from claudewatch.ui.menu.core import (  # noqa: F401
    AppDelegate,
    MenuCallback,
    add_summary_lines,
    disabled_item,
    make_menu_item,
    noop,
    style_summary_item,
)
