"""Preferences window — orchestration, sidebar, pane routing."""

from __future__ import annotations

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBox,
    NSButton,
    NSColor,
    NSFont,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect

from claudewatch.ui.preferences.delegate import PrefsDelegate
from claudewatch.ui.preferences.panes import about, guide, sessions, settings, usage

_W = 660
_H = 620
_SIDEBAR_W = 170
_CONTENT_W = _W - _SIDEBAR_W
_ROW_H = 36

_SIDEBAR_ITEMS = [
    {"type": "static", "key": "general", "label": "Settings"},
    {"type": "static", "key": "history", "label": "Sessions"},
    {"type": "static", "key": "usage", "label": "Usage"},
    {"type": "separator"},
    {"type": "static", "key": "guide", "label": "Guide"},
    {"type": "static", "key": "about", "label": "About"},
]

_PANE_BUILDERS = {
    "general": settings.build_settings_pane,
    "history": sessions.build_sessions_pane,
    "usage": usage.build_usage_pane,
    "guide": guide.build_guide_pane,
    "about": about.build_about_pane,
}

_window: NSWindow | None = None
_delegate: PrefsDelegate | None = None


def show_preferences(pane: str | None = None) -> None:
    """Show or bring to front the preferences window."""
    global _window, _delegate  # noqa: PLW0603

    if _window is not None:
        _window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        if pane and _delegate is not None:
            _select_pane_by_key(_delegate, pane)
        return

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    _delegate = PrefsDelegate.alloc().init()
    _delegate._sidebar_items = list(_SIDEBAR_ITEMS)
    _delegate._pane_builders = _PANE_BUILDERS
    _delegate._content_w = _CONTENT_W
    _delegate._content_h = _H
    _delegate._feature_controls = {}
    _delegate._current_pane = None
    _delegate._selected_idx = -1
    _delegate._history_search = ""
    _delegate._history_sort = "date"
    _delegate._history_sort_asc = False
    _delegate._history_bookmarked_only = False
    _delegate._history_scroll = None
    _delegate._history_inner = None

    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(200, 200, _W, _H), style, NSBackingStoreBuffered, False
    )
    window.setTitle_("ClaudeWatch")
    window.setDelegate_(_delegate)
    window.setReleasedWhenClosed_(False)

    root = window.contentView()

    sidebar = _build_sidebar(_delegate)
    root.addSubview_(sidebar)

    content = NSView.alloc().initWithFrame_(NSMakeRect(_SIDEBAR_W, 0, _CONTENT_W, _H))
    root.addSubview_(content)
    _delegate._content_area = content

    # Select initial pane
    target_key = pane
    if not target_key:
        target_key = next((item["key"] for item in _SIDEBAR_ITEMS if item["type"] != "separator"), "general")
    _select_pane_by_key(_delegate, target_key)

    _window = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


def _select_pane_by_key(delegate: PrefsDelegate, key: str) -> None:
    """Find sidebar item by key and select it."""
    for i, item in enumerate(delegate._sidebar_items):
        if item.get("key") == key:
            delegate.select_sidebar(i)
            return


def _build_sidebar(delegate: PrefsDelegate) -> NSView:
    """Build the sidebar navigation."""
    sidebar = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _SIDEBAR_W, _H))
    sidebar.setWantsLayer_(True)
    sidebar.layer().setBackgroundColor_(
        NSColor.windowBackgroundColor().blendedColorWithFraction_ofColor_(0.03, NSColor.blackColor()).CGColor()
    )

    btns: list[NSButton | None] = []
    y = _H - 8

    for i, item in enumerate(_SIDEBAR_ITEMS):
        if item["type"] == "separator":
            y -= 6
            sep = NSBox.alloc().initWithFrame_(NSMakeRect(12, y, _SIDEBAR_W - 24, 1))
            sep.setBoxType_(2)
            sidebar.addSubview_(sep)
            y -= 6
            btns.append(None)
            continue

        y -= _ROW_H
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(8, y, _SIDEBAR_W - 16, _ROW_H - 4))
        btn.setTitle_(f"  {item['label']}")
        btn.setBezelStyle_(0)
        btn.setBordered_(False)
        btn.setFont_(NSFont.systemFontOfSize_(13.0))
        btn.setAlignment_(0)  # left
        btn.setWantsLayer_(True)
        btn.layer().setCornerRadius_(6.0)
        btn.setTag_(i)
        btn.setTarget_(delegate)
        btn.setAction_(objc.selector(delegate.sidebarClicked_, signature=b"v@:@"))
        sidebar.addSubview_(btn)
        btns.append(btn)

    # Right edge separator
    edge = NSBox.alloc().initWithFrame_(NSMakeRect(_SIDEBAR_W - 1, 0, 1, _H))
    edge.setBoxType_(2)
    sidebar.addSubview_(edge)

    delegate._sidebar_btns = btns
    return sidebar
