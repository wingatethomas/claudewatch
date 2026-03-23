"""Toolbar-tabbed preferences window with NSTableView history."""

import os
import re
import subprocess
import webbrowser

import objc
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBox,
    NSButton,
    NSButtonTypeSwitch,
    NSColor,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSMenu,
    NSMenuItem,
    NSMutableAttributedString,
    NSPopUpButton,
    NSSegmentedControl,
    NSSegmentStyleTexturedRounded,
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
from Foundation import NSMakeRect, NSObject, NSRange, NSSortDescriptor

from claudewatch import __version__
from claudewatch.backend.helpers import escape_applescript, run_applescript
from claudewatch.backend.repositories.bookmarks import get_pinned_cwds
from claudewatch.backend.repositories.config import get_available_sounds, get_setting, set_setting
from claudewatch.backend.repositories.history import get_history, remove_history_entry
from claudewatch.backend.services.usage import MODEL_DISPLAY_NAMES
from claudewatch.ui.activity import show_activity

_REPO_URL = "https://github.com/wingatethomas/claudewatch"

_W = 680
_H = 500
_PAD = 20
_TOOLBAR_H = 36

_window: NSWindow | None = None
_delegate: "_PrefsDelegate | None" = None
_history_data: list[dict] = []


# ── Delegate ──────────────────────────────────────────────────────────


class _PrefsDelegate(NSObject):  # noqa: PLR0904
    """Handles preferences window actions, toolbar tabs, and history table."""

    _sessions_view: NSView | None = None
    _settings_view: NSView | None = None

    # ── Settings actions ──

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

    def viewUsageStats_(self, sender: objc.objc_object) -> None:
        run_applescript("""
            tell application "Terminal"
                activate
                do script "claude"
            end tell
        """)

    # ── History actions ──

    def deleteHistoryEntry_(self, sender: objc.objc_object) -> None:
        cwd = str(sender.representedObject())
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Delete this session from history?")
        alert.setInformativeText_("This cannot be undone.")
        alert.addButtonWithTitle_("Delete")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() == NSAlertFirstButtonReturn:
            remove_history_entry(cwd)
            _reload_history_data()
            self._history_table.reloadData()

    def resumeSession_(self, sender: objc.objc_object) -> None:
        data = str(sender.representedObject())
        if "|" not in data:
            return
        sid, cwd = data.split("|", 1)
        if not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", sid):
            return
        safe_cwd = escape_applescript(cwd) if cwd else ""
        cd_cmd = f'cd \\"{safe_cwd}\\" && ' if safe_cwd else ""
        run_applescript(f'''
            tell application "Terminal"
                activate
                do script "{cd_cmd}claude -r {sid}"
            end tell
        ''')

    def viewActivity_(self, sender: objc.objc_object) -> None:
        data = str(sender.representedObject())
        if "|" not in data:
            return
        project, cwd = data.split("|", 1)
        show_activity(project, cwd)

    # ── Toolbar tab switching ──

    def tabChanged_(self, sender: objc.objc_object) -> None:
        idx = sender.selectedSegment()
        if self._sessions_view and self._settings_view:
            self._settings_view.setHidden_(idx != 0)
            self._sessions_view.setHidden_(idx != 1)

    # ── NSTableView data source ──

    _history_table: NSTableView | None = None

    def numberOfRowsInTableView_(self, table: objc.objc_object) -> int:
        return len(_history_data)

    def tableView_objectValueForTableColumn_row_(
        self,
        table: objc.objc_object,
        col: objc.objc_object,
        row: int,
    ) -> str:
        if row >= len(_history_data):
            return ""
        entry = _history_data[row]
        col_id = str(col.identifier())
        if col_id == "project":
            pinned = entry.get("cwd", "") in get_pinned_cwds()
            return f"{entry.get('project', 'unknown')}{'  ★' if pinned else ''}"
        if col_id == "date":
            return entry.get("ended_at", "")[:16].replace("T", " ")
        if col_id == "model":
            raw = entry.get("model", "")
            return MODEL_DISPLAY_NAMES.get(raw, raw)
        return ""

    def tableView_sortDescriptorsDidChange_(
        self,
        table: objc.objc_object,
        old: objc.objc_object,
    ) -> None:
        descriptors = table.sortDescriptors()
        if not descriptors or len(descriptors) == 0:
            return
        desc = descriptors[0]
        key = str(desc.key())
        ascending = desc.ascending()
        col_map = {"project": "project", "date": "ended_at", "model": "model"}
        sort_key = col_map.get(key, "ended_at")
        _history_data.sort(key=lambda e: e.get(sort_key, ""), reverse=not ascending)
        table.reloadData()

    # ── History toolbar actions (act on selected row) ──

    def _selected_entry(self) -> dict | None:
        table = self._history_table
        if table is None:
            return None
        row = table.selectedRow()
        if row < 0 or row >= len(_history_data):
            return None
        return _history_data[row]

    def resumeSelected_(self, sender: objc.objc_object) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        sender.setRepresentedObject_(f"{entry.get('session_id', '')}|{entry.get('cwd', '')}")
        self.resumeSession_(sender)

    def activitySelected_(self, sender: objc.objc_object) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        sender.setRepresentedObject_(f"{entry.get('project', '')}|{entry.get('cwd', '')}")
        self.viewActivity_(sender)

    def deleteSelected_(self, sender: objc.objc_object) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        sender.setRepresentedObject_(entry.get("cwd", ""))
        self.deleteHistoryEntry_(sender)

    # ── Window close ──

    def windowWillClose_(self, notification: objc.objc_object) -> None:
        global _window  # noqa: PLW0603
        _window = None


# ── Helpers ──────────────────────────────────────────────────────────


def _reload_history_data() -> None:
    global _history_data  # noqa: PLW0603
    _history_data = get_history()


def _make_context_menu(delegate: _PrefsDelegate, entry: dict) -> NSMenu:
    """Build right-click context menu for a history row."""
    sid = entry.get("session_id", "")
    proj = entry.get("project", "unknown")
    cwd = entry.get("cwd", "")

    menu = NSMenu.alloc().init()
    resume = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Resume", "resumeSession:", "")
    resume.setTarget_(delegate)
    resume.setRepresentedObject_(f"{sid}|{cwd}")
    menu.addItem_(resume)

    activity = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Activity", "viewActivity:", "")
    activity.setTarget_(delegate)
    activity.setRepresentedObject_(f"{proj}|{cwd}")
    menu.addItem_(activity)

    menu.addItem_(NSMenuItem.separatorItem())

    delete = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Delete", "deleteHistoryEntry:", "")
    delete.setTarget_(delegate)
    delete.setRepresentedObject_(cwd)
    delete_attr = NSMutableAttributedString.alloc().initWithString_("Delete")
    delete_attr.addAttribute_value_range_("NSColor", NSColor.systemRedColor(), NSRange(0, 6))
    delete.setAttributedTitle_(delete_attr)
    menu.addItem_(delete)

    return menu


# ── Build panes ──────────────────────────────────────────────────────


def _build_sessions_pane(delegate: _PrefsDelegate) -> NSView:  # noqa: PLR0915
    """Build the Sessions pane with an NSTableView for history."""
    content_h = _H - _TOOLBAR_H
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, content_h))

    _reload_history_data()

    if not _history_data:
        empty = NSTextField.labelWithString_("No session history yet.")
        empty.setFrame_(NSMakeRect(_PAD, content_h // 2, _W - _PAD * 2, 20))
        empty.setFont_(NSFont.systemFontOfSize_(13.0))
        empty.setTextColor_(NSColor.secondaryLabelColor())
        empty.setAlignment_(1)  # center
        view.addSubview_(empty)
        return view

    # Bottom toolbar with action buttons
    _bar_h = 36
    bar = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _bar_h))

    resume_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD, 6, 28, 24))
    resume_btn.setTitle_("▶")
    resume_btn.setBezelStyle_(1)
    resume_btn.setToolTip_("Resume session")
    resume_btn.setTarget_(delegate)
    resume_btn.setAction_(objc.selector(delegate.resumeSelected_, signature=b"v@:@"))
    bar.addSubview_(resume_btn)

    activity_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD + 34, 6, 28, 24))
    activity_btn.setTitle_("ℹ")
    activity_btn.setBezelStyle_(1)
    activity_btn.setToolTip_("View session activity log")
    activity_btn.setTarget_(delegate)
    activity_btn.setAction_(objc.selector(delegate.activitySelected_, signature=b"v@:@"))
    bar.addSubview_(activity_btn)

    delete_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD + 68, 6, 28, 24))
    delete_btn.setTitle_("⛔")
    delete_btn.setBezelStyle_(1)
    delete_btn.setToolTip_("Delete from history")
    delete_btn.setTarget_(delegate)
    delete_btn.setAction_(objc.selector(delegate.deleteSelected_, signature=b"v@:@"))
    bar.addSubview_(delete_btn)

    sep = NSBox.alloc().initWithFrame_(NSMakeRect(0, _bar_h - 1, _W, 1))
    sep.setBoxType_(2)
    bar.addSubview_(sep)
    view.addSubview_(bar)

    scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(0, _bar_h, _W, content_h - _bar_h))
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)

    table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, content_h - _bar_h))
    table.setUsesAlternatingRowBackgroundColors_(True)
    table.setRowHeight_(24)
    table.setGridStyleMask_(1)  # horizontal grid lines

    # Columns (all non-editable)
    col_project = NSTableColumn.alloc().initWithIdentifier_("project")
    col_project.headerCell().setStringValue_("Project")
    col_project.setWidth_(220)
    col_project.setEditable_(False)
    col_project.setSortDescriptorPrototype_(NSSortDescriptor.alloc().initWithKey_ascending_("project", True))
    table.addTableColumn_(col_project)

    col_date = NSTableColumn.alloc().initWithIdentifier_("date")
    col_date.headerCell().setStringValue_("Last Active")
    col_date.setWidth_(150)
    col_date.setEditable_(False)
    col_date.setSortDescriptorPrototype_(NSSortDescriptor.alloc().initWithKey_ascending_("date", False))
    table.addTableColumn_(col_date)

    col_model = NSTableColumn.alloc().initWithIdentifier_("model")
    col_model.headerCell().setStringValue_("Model")
    col_model.setWidth_(120)
    col_model.setEditable_(False)
    col_model.setSortDescriptorPrototype_(NSSortDescriptor.alloc().initWithKey_ascending_("model", True))
    table.addTableColumn_(col_model)

    table.setDataSource_(delegate)
    table.setDelegate_(delegate)
    delegate._history_table = table

    scroll.setDocumentView_(table)
    view.addSubview_(scroll)

    return view


def _add_section_header(view: NSView, text: str, y: float) -> None:
    header = NSTextField.labelWithString_(text)
    header.setFrame_(NSMakeRect(_PAD, y, 300, 14))
    header.setFont_(NSFont.systemFontOfSize_(11.0))
    header.setTextColor_(NSColor.tertiaryLabelColor())
    view.addSubview_(header)


def _add_section_separator(view: NSView, y: float) -> None:
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y, _W - _PAD * 2, 1))
    sep.setBoxType_(2)
    view.addSubview_(sep)


def _add_notifications_section(view: NSView, delegate: _PrefsDelegate, y: float) -> float:
    _add_section_header(view, "NOTIFICATIONS", y)
    y -= 28

    toggle = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD, y, _W - _PAD * 2, 20))
    toggle.setButtonType_(NSButtonTypeSwitch)
    toggle.setTitle_("Enable notifications")
    toggle.setFont_(NSFont.systemFontOfSize_(13.0))
    toggle.setState_(NSControlStateValueOn if get_setting("notifications_enabled") else NSControlStateValueOff)
    toggle.setTarget_(delegate)
    toggle.setAction_(objc.selector(delegate.notificationsToggled_, signature=b"v@:@"))
    view.addSubview_(toggle)

    y -= 30
    sound_label = NSTextField.labelWithString_("Alert sound")
    sound_label.setFrame_(NSMakeRect(_PAD, y, 80, 20))
    sound_label.setFont_(NSFont.systemFontOfSize_(13.0))
    view.addSubview_(sound_label)

    sound_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(_PAD + 90, y - 2, 200, 22),
        False,
    )
    sound_popup.setFont_(NSFont.systemFontOfSize_(13.0))
    sound_popup.setToolTip_("System sounds from /System/Library/Sounds/")
    sound_popup.addItemsWithTitles_(list(get_available_sounds()))
    sound_popup.selectItemWithTitle_(str(get_setting("notification_sound")))
    sound_popup.setTarget_(delegate)
    sound_popup.setAction_(objc.selector(delegate.soundChanged_, signature=b"v@:@"))
    view.addSubview_(sound_popup)
    return y


def _add_sessions_section(view: NSView, delegate: _PrefsDelegate, y: float) -> float:
    _add_section_separator(view, y + 10)
    _add_section_header(view, "SESSIONS", y - 10)
    y -= 38

    expiry_label = NSTextField.labelWithString_("Pin expiry")
    expiry_label.setFrame_(NSMakeRect(_PAD, y, 80, 20))
    expiry_label.setFont_(NSFont.systemFontOfSize_(13.0))
    view.addSubview_(expiry_label)

    expiry_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(_PAD + 90, y - 2, 200, 22),
        False,
    )
    expiry_popup.setFont_(NSFont.systemFontOfSize_(13.0))
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

    y -= 22
    hint = NSTextField.labelWithString_("Pinned sessions expire after this period of inactivity.")
    hint.setFrame_(NSMakeRect(_PAD, y, _W - _PAD * 2, 14))
    hint.setFont_(NSFont.systemFontOfSize_(11.0))
    hint.setTextColor_(NSColor.tertiaryLabelColor())
    view.addSubview_(hint)
    return y


def _add_usage_section(view: NSView, delegate: _PrefsDelegate, y: float) -> float:
    _add_section_separator(view, y + 10)
    _add_section_header(view, "USAGE", y - 10)
    y -= 36

    usage_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD, y, 200, 28))
    usage_btn.setTitle_("View Usage Statistics")
    usage_btn.setBezelStyle_(1)
    usage_btn.setTarget_(delegate)
    usage_btn.setAction_(objc.selector(delegate.viewUsageStats_, signature=b"v@:@"))
    view.addSubview_(usage_btn)

    y -= 20
    hint = NSTextField.labelWithString_("Opens Claude Code usage in Terminal")
    hint.setFrame_(NSMakeRect(_PAD, y, _W - _PAD * 2, 14))
    hint.setFont_(NSFont.systemFontOfSize_(11.0))
    hint.setTextColor_(NSColor.tertiaryLabelColor())
    view.addSubview_(hint)
    return y


def _add_about_section(view: NSView, delegate: _PrefsDelegate, y: float) -> float:
    _add_section_separator(view, y + 10)
    _add_section_header(view, "ABOUT", y - 10)
    y -= 36

    ver_label = NSTextField.labelWithString_(f"ClaudeWatch v{__version__}")
    ver_label.setFrame_(NSMakeRect(_PAD, y, 200, 18))
    ver_label.setFont_(NSFont.systemFontOfSize_(13.0))
    view.addSubview_(ver_label)

    y -= 28
    log_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD, y, 110, 28))
    log_btn.setTitle_("Audit Log")
    log_btn.setBezelStyle_(1)
    log_btn.setTarget_(delegate)
    log_btn.setAction_(objc.selector(delegate.viewAuditLog_, signature=b"v@:@"))
    view.addSubview_(log_btn)

    repo_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD + 120, y, 90, 28))
    repo_btn.setTitle_("GitHub")
    repo_btn.setBezelStyle_(1)
    repo_btn.setTarget_(delegate)
    repo_btn.setAction_(objc.selector(delegate.openRepo_, signature=b"v@:@"))
    view.addSubview_(repo_btn)
    return y


def _build_settings_pane(delegate: _PrefsDelegate) -> NSView:
    """Build the Settings pane with all preferences."""
    content_h = _H - _TOOLBAR_H
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, content_h))

    # Vertically center the content (~320px of settings in ~464px pane)
    _content_height = 340
    y = (content_h + _content_height) // 2

    y = _add_notifications_section(view, delegate, y)
    y -= 44
    y = _add_sessions_section(view, delegate, y)
    y -= 34
    y = _add_usage_section(view, delegate, y)
    y -= 34
    _add_about_section(view, delegate, y)

    return view


# ── Public API ────────────────────────────────────────────────────────


def show_preferences() -> None:
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
    window.setTitle_("ClaudeWatch")
    window.setDelegate_(_delegate)
    window.setReleasedWhenClosed_(False)

    root = window.contentView()

    # Toolbar: segmented control for Sessions / Settings
    seg = NSSegmentedControl.alloc().initWithFrame_(
        NSMakeRect((_W - 240) // 2, _H - _TOOLBAR_H, 240, 28),
    )
    seg.setSegmentCount_(2)
    seg.setLabel_forSegment_("Preferences", 0)
    seg.setLabel_forSegment_("History", 1)
    seg.setWidth_forSegment_(115, 0)
    seg.setWidth_forSegment_(115, 1)
    seg.setSegmentStyle_(NSSegmentStyleTexturedRounded)
    seg.setSelectedSegment_(0)
    seg.setTarget_(_delegate)
    seg.setAction_(objc.selector(_delegate.tabChanged_, signature=b"v@:@"))
    root.addSubview_(seg)

    # Separator under toolbar
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(0, _H - _TOOLBAR_H - 2, _W, 1))
    sep.setBoxType_(2)
    root.addSubview_(sep)

    # Build panes
    content_y = 0
    content_h = _H - _TOOLBAR_H - 2

    settings_view = _build_settings_pane(_delegate)
    settings_view.setFrame_(NSMakeRect(0, content_y, _W, content_h))
    settings_view.setHidden_(False)
    root.addSubview_(settings_view)
    _delegate._settings_view = settings_view

    sessions_view = _build_sessions_pane(_delegate)
    sessions_view.setFrame_(NSMakeRect(0, content_y, _W, content_h))
    sessions_view.setHidden_(True)
    root.addSubview_(sessions_view)
    _delegate._sessions_view = sessions_view

    _window = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
