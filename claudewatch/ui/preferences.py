"""Sidebar-based preferences window using PyObjC."""

import os
import subprocess
import webbrowser

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBox,
    NSButton,
    NSButtonTypeSwitch,
    NSColor,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSMutableAttributedString,
    NSPopUpButton,
    NSSound,
    NSTableColumn,
    NSTableView,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from AppKit import NSScrollView as AppKitScrollView
from Foundation import NSMakeRect, NSObject, NSRange

from claudewatch import __version__
from claudewatch.backend.repositories.config import get_available_sounds, get_setting, set_setting

_REPO_URL = "https://github.com/wingatethomas/claudewatch"
_W = 520
_H = 320
_SIDEBAR_W = 140
_CONTENT_W = _W - _SIDEBAR_W
_PAD = 20

_window: NSWindow | None = None
_delegate: "_PrefsDelegate | None" = None
_content_views: dict[str, NSView] = {}

_SECTIONS = ["General", "Sessions", "About"]


class _PrefsDelegate(NSObject):
    """Handles preferences window actions and sidebar selection."""

    _content_container = None

    def notificationsToggled_(self, sender: objc.objc_object) -> None:
        set_setting("notifications_enabled", sender.state() == NSControlStateValueOn)

    def soundChanged_(self, sender: objc.objc_object) -> None:
        sound_name = sender.titleOfSelectedItem()
        set_setting("notification_sound", sound_name)
        sound = NSSound.soundNamed_(sound_name)
        if sound:
            sound.play()

    def expiryChanged_(self, sender: objc.objc_object) -> None:
        title = sender.titleOfSelectedItem()
        days = 0 if title == "Never" else int(title.rstrip(" days"))
        set_setting("pin_expiry_days", days)

    def viewAuditLog_(self, sender: objc.objc_object) -> None:
        log_path = os.path.expanduser("~/.claude/claudewatch.log")
        if os.path.exists(log_path):
            subprocess.run(["open", "-a", "Console", log_path], check=False)  # noqa: S603, S607

    def openRepo_(self, sender: objc.objc_object) -> None:
        webbrowser.open(_REPO_URL)

    def windowWillClose_(self, notification: objc.objc_object) -> None:
        global _window  # noqa: PLW0603
        _window = None

    # NSTableView data source / delegate
    def numberOfRowsInTableView_(self, table: objc.objc_object) -> int:
        return len(_SECTIONS)

    def tableView_objectValueForTableColumn_row_(
        self, table: objc.objc_object, col: objc.objc_object, row: int,
    ) -> str:
        return _SECTIONS[row]

    def tableViewSelectionDidChange_(self, notification: objc.objc_object) -> None:
        table = notification.object()
        row = table.selectedRow()
        if row < 0:
            return
        section = _SECTIONS[row]
        container = self._content_container
        if container is None:
            return
        for sub in container.subviews():
            sub.setHidden_(True)
        view = _content_views.get(section)
        if view:
            view.setHidden_(False)


def _build_general_view(delegate: _PrefsDelegate) -> NSView:
    """Build the General settings pane."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _CONTENT_W, _H))
    y = _H - 40

    header = NSTextField.labelWithString_("General")
    header.setFrame_(NSMakeRect(_PAD, y, 200, 22))
    header.setFont_(NSFont.boldSystemFontOfSize_(15.0))
    view.addSubview_(header)

    y -= 36

    checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD, y, _CONTENT_W - _PAD * 2, 20))
    checkbox.setButtonType_(NSButtonTypeSwitch)
    checkbox.setTitle_("Enable notifications")
    checkbox.setFont_(NSFont.systemFontOfSize_(13.0))
    checkbox.setState_(NSControlStateValueOn if get_setting("notifications_enabled") else NSControlStateValueOff)
    checkbox.setTarget_(delegate)
    checkbox.setAction_(objc.selector(delegate.notificationsToggled_, signature=b"v@:@"))
    view.addSubview_(checkbox)

    y -= 32

    sound_label = NSTextField.labelWithString_("Alert sound")
    sound_label.setFrame_(NSMakeRect(_PAD, y, 80, 20))
    sound_label.setFont_(NSFont.systemFontOfSize_(13.0))
    sound_label.setTextColor_(NSColor.secondaryLabelColor())
    view.addSubview_(sound_label)

    sound_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(_PAD + 90, y - 2, _CONTENT_W - _PAD * 2 - 90, 24), False,
    )
    sound_popup.setFont_(NSFont.systemFontOfSize_(12.0))
    sound_popup.addItemsWithTitles_(list(get_available_sounds()))
    sound_popup.selectItemWithTitle_(str(get_setting("notification_sound")))
    sound_popup.setTarget_(delegate)
    sound_popup.setAction_(objc.selector(delegate.soundChanged_, signature=b"v@:@"))
    view.addSubview_(sound_popup)

    return view


def _build_sessions_view(delegate: _PrefsDelegate) -> NSView:
    """Build the Sessions settings pane."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _CONTENT_W, _H))
    y = _H - 40

    header = NSTextField.labelWithString_("Sessions")
    header.setFrame_(NSMakeRect(_PAD, y, 200, 22))
    header.setFont_(NSFont.boldSystemFontOfSize_(15.0))
    view.addSubview_(header)

    y -= 36

    expiry_label = NSTextField.labelWithString_("Pin expiry")
    expiry_label.setFrame_(NSMakeRect(_PAD, y, 80, 20))
    expiry_label.setFont_(NSFont.systemFontOfSize_(13.0))
    expiry_label.setTextColor_(NSColor.secondaryLabelColor())
    view.addSubview_(expiry_label)

    expiry_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(_PAD + 90, y - 2, _CONTENT_W - _PAD * 2 - 90, 24), False,
    )
    expiry_popup.setFont_(NSFont.systemFontOfSize_(12.0))
    options = ["Never", "7 days", "14 days", "30 days", "60 days", "90 days"]
    expiry_popup.addItemsWithTitles_(options)
    current = int(get_setting("pin_expiry_days") or 30)
    if current <= 0:
        expiry_popup.selectItemWithTitle_("Never")
    else:
        expiry_popup.selectItemWithTitle_(f"{current} days")
    expiry_popup.setTarget_(delegate)
    expiry_popup.setAction_(objc.selector(delegate.expiryChanged_, signature=b"v@:@"))
    view.addSubview_(expiry_popup)

    y -= 28

    hint = NSTextField.labelWithString_("Pinned sessions expire after this period of inactivity.")
    hint.setFrame_(NSMakeRect(_PAD, y, _CONTENT_W - _PAD * 2, 16))
    hint.setFont_(NSFont.systemFontOfSize_(11.0))
    hint.setTextColor_(NSColor.tertiaryLabelColor())
    view.addSubview_(hint)

    return view


def _build_about_view(delegate: _PrefsDelegate) -> NSView:
    """Build the About pane."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _CONTENT_W, _H))
    y = _H - 40

    # Title with version
    name_field = NSTextField.labelWithString_("")
    name_field.setFrame_(NSMakeRect(_PAD, y, _CONTENT_W - _PAD * 2, 22))
    title_str = NSMutableAttributedString.alloc().initWithString_(f"✦ ClaudeWatch  v{__version__}")
    bold_len = len("✦ ClaudeWatch  ")
    ver_len = len(f"v{__version__}")
    title_str.addAttribute_value_range_("NSFont", NSFont.boldSystemFontOfSize_(15.0), NSRange(0, bold_len))
    title_str.addAttribute_value_range_("NSFont", NSFont.systemFontOfSize_(11.0), NSRange(bold_len, ver_len))
    title_str.addAttribute_value_range_("NSColor", NSColor.tertiaryLabelColor(), NSRange(bold_len, ver_len))
    name_field.setAttributedStringValue_(title_str)
    view.addSubview_(name_field)

    y -= 24

    desc = NSTextField.labelWithString_("macOS menu bar app for monitoring Claude Code sessions.")
    desc.setFrame_(NSMakeRect(_PAD, y, _CONTENT_W - _PAD * 2, 16))
    desc.setFont_(NSFont.systemFontOfSize_(11.0))
    desc.setTextColor_(NSColor.secondaryLabelColor())
    view.addSubview_(desc)

    y -= 36

    log_button = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD, y, 110, 28))
    log_button.setTitle_("Audit Log")
    log_button.setBezelStyle_(1)
    log_button.setTarget_(delegate)
    log_button.setAction_(objc.selector(delegate.viewAuditLog_, signature=b"v@:@"))
    view.addSubview_(log_button)

    repo_button = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD + 120, y, 90, 28))
    repo_button.setTitle_("GitHub")
    repo_button.setBezelStyle_(1)
    repo_button.setTarget_(delegate)
    repo_button.setAction_(objc.selector(delegate.openRepo_, signature=b"v@:@"))
    view.addSubview_(repo_button)

    return view


def show_preferences() -> None:  # noqa: PLR0915
    """Show (or bring to front) the preferences window."""
    global _window, _delegate  # noqa: PLW0603

    if _window is not None:
        _window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        return

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    _delegate = _PrefsDelegate.alloc().init()

    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(200, 200, _W, _H),
        style,
        2,
        False,
    )
    window.setTitle_("Preferences")
    window.setDelegate_(_delegate)
    window.setReleasedWhenClosed_(False)

    root = window.contentView()

    # Sidebar background
    sidebar_bg = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _SIDEBAR_W, _H))
    sidebar_bg.setWantsLayer_(True)
    sidebar_bg.layer().setBackgroundColor_(NSColor.controlBackgroundColor().CGColor())
    root.addSubview_(sidebar_bg)

    # Sidebar table
    sidebar_scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, _SIDEBAR_W, _H))
    sidebar_scroll.setHasVerticalScroller_(False)
    sidebar_scroll.setDrawsBackground_(False)

    table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, _SIDEBAR_W, _H))
    col = NSTableColumn.alloc().initWithIdentifier_("name")
    col.setWidth_(_SIDEBAR_W - 4)
    table.addTableColumn_(col)
    table.setHeaderView_(None)
    table.setDataSource_(_delegate)
    table.setDelegate_(_delegate)
    table.setRowHeight_(28)
    table.setBackgroundColor_(NSColor.clearColor())

    sidebar_scroll.setDocumentView_(table)
    root.addSubview_(sidebar_scroll)

    # Separator
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(_SIDEBAR_W, 0, 1, _H))
    sep.setBoxType_(2)
    root.addSubview_(sep)

    # Content area
    content_container = NSView.alloc().initWithFrame_(NSMakeRect(_SIDEBAR_W, 0, _CONTENT_W, _H))
    _delegate._content_container = content_container
    root.addSubview_(content_container)

    # Build panes
    _content_views.clear()
    _content_views["General"] = _build_general_view(_delegate)
    _content_views["Sessions"] = _build_sessions_view(_delegate)
    _content_views["About"] = _build_about_view(_delegate)

    for name, pane in _content_views.items():
        pane.setFrame_(NSMakeRect(0, 0, _CONTENT_W, _H))
        pane.setHidden_(name != "General")
        content_container.addSubview_(pane)

    # Select first row
    table.selectRowIndexes_byExtendingSelection_(
        __import__("Foundation").NSIndexSet.indexSetWithIndex_(0), False,
    )

    _window = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
