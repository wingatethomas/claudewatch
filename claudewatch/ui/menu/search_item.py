"""Search field hosted in a menu item — filters the active-session rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

import objc
from AppKit import (
    NSControlSizeLarge,
    NSEventTrackingRunLoopMode,
    NSMakeRect,
    NSMenuItem,
    NSSearchField,
    NSView,
    NSViewWidthSizable,
)
from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer

from claudewatch.ui.components.tokens import Font, Spacing

if TYPE_CHECKING:
    from claudewatch.ui.menu.core import AppDelegate

_ITEM_WIDTH = 260
_ITEM_HEIGHT = 38
_FIELD_HEIGHT = 28

SEARCH_DEBOUNCE_SECONDS = 0.25


def build_search_item(delegate: AppDelegate) -> tuple[NSMenuItem, NSSearchField]:
    """Create the persistent search menu item and its field, wired to the delegate."""
    container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _ITEM_WIDTH, _ITEM_HEIGHT))
    container.setAutoresizingMask_(NSViewWidthSizable)
    field_width = _ITEM_WIDTH - 2 * Spacing.MD
    field_y = (_ITEM_HEIGHT - _FIELD_HEIGHT) / 2
    search_field = NSSearchField.alloc().initWithFrame_(NSMakeRect(Spacing.MD, field_y, field_width, _FIELD_HEIGHT))
    search_field.setPlaceholderString_("Filter sessions…")
    search_field.setControlSize_(NSControlSizeLarge)
    search_field.setFont_(Font.body())
    search_field.setTarget_(delegate)
    search_field.setAction_(objc.selector(delegate.sessionSearchChanged_, signature=b"v@:@"))
    search_field.setDelegate_(delegate)
    search_field.setAutoresizingMask_(NSViewWidthSizable)
    container.addSubview_(search_field)
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, "")
    item.setView_(container)
    return item, search_field


def schedule_search_debounce(delegate: AppDelegate, query: str) -> NSTimer:
    """Schedule the debounced filter apply; tracking mode so it fires while the menu is open."""
    timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
        SEARCH_DEBOUNCE_SECONDS,
        delegate,
        "searchDebounceFired:",
        query,
        False,
    )
    run_loop = NSRunLoop.currentRunLoop()
    run_loop.addTimer_forMode_(timer, NSRunLoopCommonModes)
    run_loop.addTimer_forMode_(timer, NSEventTrackingRunLoopMode)
    return timer
