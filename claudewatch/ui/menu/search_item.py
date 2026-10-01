"""Search field hosted in a menu item — filters the active-session rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

import objc
from AppKit import (
    NSMakeRect,
    NSMenuItem,
    NSSearchField,
    NSView,
    NSViewWidthSizable,
)

from claudewatch.ui.components.tokens import Font, Spacing

if TYPE_CHECKING:
    from claudewatch.ui.menu.core import AppDelegate

_ITEM_WIDTH = 260
_ITEM_HEIGHT = 30
_FIELD_HEIGHT = 22


def build_search_item(delegate: AppDelegate) -> tuple[NSMenuItem, NSSearchField]:
    """Create the persistent search menu item and its field, wired to the delegate."""
    container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _ITEM_WIDTH, _ITEM_HEIGHT))
    field_width = _ITEM_WIDTH - 2 * Spacing.MD
    field_y = (_ITEM_HEIGHT - _FIELD_HEIGHT) / 2
    search_field = NSSearchField.alloc().initWithFrame_(NSMakeRect(Spacing.MD, field_y, field_width, _FIELD_HEIGHT))
    search_field.setPlaceholderString_("Filter sessions…")
    search_field.setFont_(Font.body())
    search_field.setSendsSearchStringImmediately_(True)
    search_field.setTarget_(delegate)
    search_field.setAction_(objc.selector(delegate.sessionSearchChanged_, signature=b"v@:@"))
    search_field.setAutoresizingMask_(NSViewWidthSizable)
    container.addSubview_(search_field)
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, "")
    item.setView_(container)
    return item, search_field
