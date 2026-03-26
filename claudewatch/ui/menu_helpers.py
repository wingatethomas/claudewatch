"""Menu item construction helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import objc
from AppKit import (
    NSColor,
    NSFont,
    NSMenu,
    NSMenuItem,
    NSMutableAttributedString,
    NSObject,
)
from Foundation import NSRange

if TYPE_CHECKING:
    from claudewatch.ui.menubar import ClaudeWatchApp

# Type alias for menu item click handlers
MenuCallback = Callable[[NSMenuItem], None]


class AppDelegate(NSObject):
    """Handles NSMenuItem actions and poll timer ticks."""

    _callbacks: dict[int, Callable]
    _next_tag: int
    _app: ClaudeWatchApp | None

    def init(self):  # noqa: ANN201, ANN202
        self = objc.super(AppDelegate, self).init()  # noqa: PLW0642
        if self is not None:
            self._callbacks = {}
            self._next_tag = 1
            self._app = None
        return self

    def menuItemClicked_(self, sender: NSMenuItem) -> None:  # noqa: N802
        cb = self._callbacks.get(sender.tag())
        if cb:
            cb(sender)

    def pollTick_(self, timer: object) -> None:  # noqa: N802, ARG002
        if self._app:
            self._app.poll()


def noop(_: NSMenuItem) -> None:
    """No-op callback — keeps menu items enabled (not greyed out)."""


def make_menu_item(title: str, callback: MenuCallback | None, delegate: AppDelegate) -> NSMenuItem:
    """Create an NSMenuItem, wiring its callback through the delegate."""
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
    if callback is not None:
        tag = delegate._next_tag
        delegate._next_tag += 1
        item.setTag_(tag)
        item.setTarget_(delegate)
        item.setAction_("menuItemClicked:")
        delegate._callbacks[tag] = callback
    return item


def disabled_item(title: str) -> NSMenuItem:
    """Create a non-selectable, non-interactive menu item (for headers/labels)."""
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
    item.setEnabled_(False)
    return item


def add_summary_lines(submenu: NSMenu, text: str, delegate: AppDelegate) -> None:
    """Split a summary into wrapped menu items — non-interactive, readable text."""
    _wrap = 55
    for raw_bullet in text.splitlines():
        stripped = raw_bullet.strip()
        if not stripped:
            continue
        # Wrap long bullets across multiple menu items
        words = stripped.split()
        line = ""
        for word in words:
            if line and len(line) + 1 + len(word) > _wrap:
                item = make_menu_item(f"  {line}", None, delegate)
                style_summary_item(item)
                submenu.addItem_(item)
                line = f"    {word}"  # indent continuation lines
            else:
                line = f"{line} {word}" if line else word
        if line:
            item = make_menu_item(f"  {line}", None, delegate)
            style_summary_item(item)
            submenu.addItem_(item)


def style_summary_item(item: NSMenuItem) -> None:
    """Apply readable font styling to a summary menu item."""
    text = str(item.title())
    attr = NSMutableAttributedString.alloc().initWithString_(text)
    r = NSRange(0, len(text))
    attr.addAttribute_value_range_("NSFont", NSFont.systemFontOfSize_(12.0), r)
    attr.addAttribute_value_range_("NSColor", NSColor.labelColor(), r)
    item.setAttributedTitle_(attr)
