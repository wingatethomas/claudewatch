"""Sidebar preferences window — macOS System Settings style."""

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
    NSColor,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSMenu,
    NSMenuItem,
    NSMutableAttributedString,
    NSPopUpButton,
    NSSound,
    NSSwitch,
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
from claudewatch.backend.bookmark.dependencies import get_bookmark_service
from claudewatch.backend.core import features
from claudewatch.backend.core.helpers import escape_applescript, run_applescript
from claudewatch.backend.core.paths import LOG_PATH
from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.usage.dependencies import get_usage_service
from claudewatch.backend.usage.service import MODEL_DISPLAY_NAMES, format_tokens_breakdown
from claudewatch.ui.activity import show_activity

_REPO_URL = "https://github.com/wingatethomas/claudewatch"

# Window dimensions
_W = 680
_H = 480
_SIDEBAR_W = 180
_CONTENT_W = _W - _SIDEBAR_W
_PAD = 20

_window: NSWindow | None = None
_delegate: "_PrefsDelegate | None" = None
_history_data: list[dict] = []


# ── Sidebar items ────────────────────────────────────────────────────


def _sidebar_items() -> list[dict]:
    """Build sidebar item list from registered features + static sections."""
    items: list[dict] = []
    for f in features.get_all():
        items.append({"type": "feature", "key": f.key, "label": f.description})
    items.append({"type": "separator"})
    items.append({"type": "static", "key": "history", "label": "History"})
    items.append({"type": "static", "key": "usage", "label": "Usage"})
    items.append({"type": "static", "key": "about", "label": "About"})
    return items


# ── Delegate ─────────────────────────────────────────────────────────


class _PrefsDelegate(NSObject):  # noqa: PLR0904
    """Handles sidebar selection, feature toggles, facets, and history table."""

    _sidebar_items: list[dict]
    _sidebar_table: NSTableView | None
    _content_area: NSView | None
    _current_pane: NSView | None
    _feature_controls: dict  # feature_key -> list of facet controls

    # ── Sidebar data source ──

    def numberOfRowsInSidebarTable_(self, table: objc.objc_object) -> int:  # noqa: N802
        return len(self._sidebar_items)

    def sidebarTable_objectValueForColumn_row_(  # noqa: N802
        self,
        table: objc.objc_object,
        col: objc.objc_object,
        row: int,
    ) -> str:
        if row >= len(self._sidebar_items):
            return ""
        item = self._sidebar_items[row]
        if item["type"] == "separator":
            return ""
        return item.get("label", "")

    def _show_pane(self, item: dict) -> None:
        """Swap the content area to show the pane for the selected sidebar item."""
        if self._current_pane is not None:
            self._current_pane.removeFromSuperview()
            self._current_pane = None

        content_h = _H
        if item["type"] == "feature":
            pane = _build_feature_pane(self, item["key"], _CONTENT_W, content_h)
        elif item["key"] == "history":
            pane = _build_history_pane(self, _CONTENT_W, content_h)
        elif item["key"] == "usage":
            pane = _build_usage_pane(_CONTENT_W, content_h)
        elif item["key"] == "about":
            pane = _build_about_pane(self, _CONTENT_W, content_h)
        else:
            return

        pane.setFrame_(NSMakeRect(0, 0, _CONTENT_W, content_h))
        self._content_area.addSubview_(pane)
        self._current_pane = pane

    # ── Feature actions ──

    def featureToggled_(self, sender: objc.objc_object) -> None:  # noqa: N802
        key = str(sender.representedObject() or sender.cell().representedObject())
        enabled = sender.state() == NSControlStateValueOn
        features.set_enabled(key, enabled)
        for ctrl in self._feature_controls.get(key, []):
            ctrl.setEnabled_(enabled)

    def facetChanged_(self, sender: objc.objc_object) -> None:  # noqa: N802
        info = str(sender.cell().representedObject())
        key, facet_name = info.split("|", 1)
        if hasattr(sender, "titleOfSelectedItem"):
            value: object = sender.titleOfSelectedItem()
        else:
            value = sender.state() == NSControlStateValueOn
        features.set_facet(key, facet_name, value)
        if key == "notifications" and facet_name == "sound":
            sound = NSSound.soundNamed_(value)
            if sound:
                sound.play()

    # ── Static actions ──

    def viewAuditLog_(self, sender: objc.objc_object) -> None:  # noqa: N802
        if os.path.exists(LOG_PATH):
            subprocess.run(["open", "-a", "Console", LOG_PATH], check=False)  # noqa: S603, S607

    def openRepo_(self, sender: objc.objc_object) -> None:  # noqa: N802
        webbrowser.open(_REPO_URL)

    # ── History actions ──

    _history_table: NSTableView | None = None
    _actions_popup: NSPopUpButton | None = None

    def deleteHistoryEntry_(self, sender: objc.objc_object) -> None:  # noqa: N802
        cwd = str(sender.representedObject())
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Delete this session from history?")
        alert.setInformativeText_("This cannot be undone.")
        alert.addButtonWithTitle_("Delete")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() == NSAlertFirstButtonReturn:
            get_history_service().remove(cwd)
            _reload_history_data()
            self._history_table.reloadData()

    def resumeSession_(self, sender: objc.objc_object) -> None:  # noqa: N802
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

    def viewActivity_(self, sender: objc.objc_object) -> None:  # noqa: N802
        data = str(sender.representedObject())
        if "|" not in data:
            return
        project, cwd = data.split("|", 1)
        show_activity(project, cwd)

    # ── History table data source ──

    def numberOfRowsInTableView_(self, table: objc.objc_object) -> int:  # noqa: N802
        return len(_history_data)

    def tableView_objectValueForTableColumn_row_(  # noqa: N802
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
            pinned = entry.get("cwd", "") in get_bookmark_service().get_pinned_cwds()
            return f"{entry.get('project', 'unknown')}{'  \u2605' if pinned else ''}"
        if col_id == "date":
            return entry.get("ended_at", "")[:16].replace("T", " ")
        if col_id == "model":
            raw = entry.get("model", "")
            return MODEL_DISPLAY_NAMES.get(raw, raw)
        return ""

    def tableView_sortDescriptorsDidChange_(  # noqa: N802
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

    def tableViewSelectionDidChange_(self, notification: objc.objc_object) -> None:  # noqa: N802
        table = notification.object()
        popup = self._actions_popup
        if popup is None:
            return
        if table.selectedRow() >= 0:
            popup.setEnabled_(True)
            popup.itemAtIndex_(0).setTitle_("Actions")
        else:
            popup.setEnabled_(False)
            popup.itemAtIndex_(0).setTitle_("Select a row")

    def _selected_entry(self) -> dict | None:
        table = self._history_table
        if table is None:
            return None
        row = table.selectedRow()
        if row < 0 or row >= len(_history_data):
            return None
        return _history_data[row]

    def resumeSelected_(self, sender: objc.objc_object) -> None:  # noqa: N802
        entry = self._selected_entry()
        if not entry:
            return
        sender.setRepresentedObject_(f"{entry.get('session_id', '')}|{entry.get('cwd', '')}")
        self.resumeSession_(sender)

    def activitySelected_(self, sender: objc.objc_object) -> None:  # noqa: N802
        entry = self._selected_entry()
        if not entry:
            return
        sender.setRepresentedObject_(f"{entry.get('project', '')}|{entry.get('cwd', '')}")
        self.viewActivity_(sender)

    def deleteSelected_(self, sender: objc.objc_object) -> None:  # noqa: N802
        entry = self._selected_entry()
        if not entry:
            return
        sender.setRepresentedObject_(entry.get("cwd", ""))
        self.deleteHistoryEntry_(sender)

    # ── Sidebar click ──

    def sidebarClicked_(self, sender: objc.objc_object) -> None:  # noqa: N802
        tag = sender.tag()
        if tag < 0 or tag >= len(self._sidebar_items):
            return
        item = self._sidebar_items[tag]
        if item["type"] != "separator":
            self._show_pane(item)

    # ── Window close ──

    def windowWillClose_(self, notification: objc.objc_object) -> None:  # noqa: N802
        global _window  # noqa: PLW0603
        _window = None


# ── Helpers ──────────────────────────────────────────────────────────


def _reload_history_data() -> None:
    global _history_data  # noqa: PLW0603
    _history_data = [e.to_dict() for e in get_history_service().get_all()]


# ── Content pane builders ────────────────────────────────────────────


def _build_feature_pane(delegate: _PrefsDelegate, feature_key: str, w: int, h: int) -> NSView:  # noqa: PLR0915
    """Build the content pane for a single feature — toggle + facets."""
    feature = next((f for f in features.get_all() if f.key == feature_key), None)
    if feature is None:
        return NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))

    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    delegate._feature_controls = getattr(delegate, "_feature_controls", {})

    y = h - _PAD - 10

    # Feature title
    title = NSTextField.labelWithString_(feature.description)
    title.setFrame_(NSMakeRect(_PAD, y, w - _PAD * 2 - 60, 24))
    title.setFont_(NSFont.boldSystemFontOfSize_(16.0))
    view.addSubview_(title)

    # Toggle switch — right aligned with title
    enabled = features.is_enabled(feature_key)
    toggle = NSSwitch.alloc().initWithFrame_(NSMakeRect(w - _PAD - 46, y + 2, 46, 22))
    toggle.setState_(NSControlStateValueOn if enabled else NSControlStateValueOff)
    toggle.setRepresentedObject_(feature_key)
    toggle.setTarget_(delegate)
    toggle.setAction_(objc.selector(delegate.featureToggled_, signature=b"v@:@"))
    view.addSubview_(toggle)

    y -= 12

    # Separator
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, 1))
    sep.setBoxType_(2)
    view.addSubview_(sep)

    y -= 24

    # Facets
    facet_controls: list[objc.objc_object] = []
    for facet in feature.facets:
        facet_label = facet.description or facet.name.replace("_", " ").title()
        label = NSTextField.labelWithString_(facet_label)
        label.setFrame_(NSMakeRect(_PAD, y + 2, 140, 18))
        label.setFont_(NSFont.systemFontOfSize_(13.0))
        label.setTextColor_(NSColor.secondaryLabelColor())
        view.addSubview_(label)

        if facet.type == "choice":
            popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(_PAD + 150, y - 1, w - _PAD * 2 - 150, 24),
                False,
            )
            popup.setFont_(NSFont.systemFontOfSize_(13.0))
            popup.addItemsWithTitles_(list(facet.options))
            current = features.get_facet(feature_key, facet.name)
            if current is not None:
                popup.selectItemWithTitle_(str(current))
            popup.cell().setRepresentedObject_(f"{feature_key}|{facet.name}")
            popup.setTarget_(delegate)
            popup.setAction_(objc.selector(delegate.facetChanged_, signature=b"v@:@"))
            popup.setEnabled_(enabled)
            view.addSubview_(popup)
            facet_controls.append(popup)
        elif facet.type == "bool":
            checkbox = NSSwitch.alloc().initWithFrame_(NSMakeRect(_PAD + 150, y, 46, 22))
            val = features.get_facet(feature_key, facet.name)
            checkbox.setState_(NSControlStateValueOn if val else NSControlStateValueOff)
            checkbox.setRepresentedObject_(f"{feature_key}|{facet.name}")
            checkbox.setTarget_(delegate)
            checkbox.setAction_(objc.selector(delegate.facetChanged_, signature=b"v@:@"))
            checkbox.setEnabled_(enabled)
            view.addSubview_(checkbox)
            facet_controls.append(checkbox)

        y -= 34

    delegate._feature_controls[feature_key] = facet_controls

    # Description hint at the bottom if no facets
    if not feature.facets:
        hint = NSTextField.labelWithString_("Toggle this feature on or off.")
        hint.setFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, 16))
        hint.setFont_(NSFont.systemFontOfSize_(11.0))
        hint.setTextColor_(NSColor.tertiaryLabelColor())
        view.addSubview_(hint)

    return view


def _build_history_pane(delegate: _PrefsDelegate, w: int, h: int) -> NSView:  # noqa: PLR0915
    """Build the history pane with an NSTableView."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))

    _reload_history_data()

    if not _history_data:
        empty = NSTextField.labelWithString_("No session history yet.")
        empty.setFrame_(NSMakeRect(_PAD, h // 2, w - _PAD * 2, 20))
        empty.setFont_(NSFont.systemFontOfSize_(13.0))
        empty.setTextColor_(NSColor.secondaryLabelColor())
        empty.setAlignment_(1)
        view.addSubview_(empty)
        return view

    # Bottom toolbar
    _bar_h = 36
    bar = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, _bar_h))

    actions_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(_PAD, 6, 100, 24),
        True,
    )
    actions_popup.setFont_(NSFont.systemFontOfSize_(12.0))
    actions_popup.setEnabled_(False)
    actions_popup.addItemWithTitle_("Select a row")
    actions_popup.addItemWithTitle_("Resume")
    actions_popup.addItemWithTitle_("Activity")
    actions_popup.addItemWithTitle_("Delete")
    actions_popup.itemAtIndex_(1).setTarget_(delegate)
    actions_popup.itemAtIndex_(1).setAction_(objc.selector(delegate.resumeSelected_, signature=b"v@:@"))
    actions_popup.itemAtIndex_(2).setTarget_(delegate)
    actions_popup.itemAtIndex_(2).setAction_(objc.selector(delegate.activitySelected_, signature=b"v@:@"))
    actions_popup.itemAtIndex_(3).setTarget_(delegate)
    actions_popup.itemAtIndex_(3).setAction_(objc.selector(delegate.deleteSelected_, signature=b"v@:@"))
    bar.addSubview_(actions_popup)

    sep = NSBox.alloc().initWithFrame_(NSMakeRect(0, _bar_h - 1, w, 1))
    sep.setBoxType_(2)
    bar.addSubview_(sep)
    view.addSubview_(bar)

    scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(0, _bar_h, w, h - _bar_h))
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)

    table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h - _bar_h))
    table.setUsesAlternatingRowBackgroundColors_(True)
    table.setRowHeight_(28)
    table.setGridStyleMask_(1)

    col_project = NSTableColumn.alloc().initWithIdentifier_("project")
    col_project.headerCell().setStringValue_("Project")
    col_project.setWidth_(180)
    col_project.setEditable_(False)
    col_project.setSortDescriptorPrototype_(NSSortDescriptor.alloc().initWithKey_ascending_("project", True))
    table.addTableColumn_(col_project)

    col_date = NSTableColumn.alloc().initWithIdentifier_("date")
    col_date.headerCell().setStringValue_("Last Active")
    col_date.setWidth_(140)
    col_date.setEditable_(False)
    col_date.setSortDescriptorPrototype_(NSSortDescriptor.alloc().initWithKey_ascending_("date", False))
    table.addTableColumn_(col_date)

    col_model = NSTableColumn.alloc().initWithIdentifier_("model")
    col_model.headerCell().setStringValue_("Model")
    col_model.setWidth_(80)
    col_model.setEditable_(False)
    col_model.setSortDescriptorPrototype_(NSSortDescriptor.alloc().initWithKey_ascending_("model", True))
    table.addTableColumn_(col_model)

    table.setColumnAutoresizingStyle_(1)
    table.setDataSource_(delegate)
    table.setDelegate_(delegate)
    delegate._history_table = table
    delegate._actions_popup = actions_popup

    # Context menu
    ctx_menu = NSMenu.alloc().init()
    ctx_resume = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Resume", "resumeSelected:", "")
    ctx_resume.setTarget_(delegate)
    ctx_menu.addItem_(ctx_resume)
    ctx_activity = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Activity", "activitySelected:", "")
    ctx_activity.setTarget_(delegate)
    ctx_menu.addItem_(ctx_activity)
    ctx_menu.addItem_(NSMenuItem.separatorItem())
    ctx_delete = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Delete", "deleteSelected:", "")
    ctx_delete.setTarget_(delegate)
    delete_attr = NSMutableAttributedString.alloc().initWithString_("Delete")
    delete_attr.addAttribute_value_range_("NSColor", NSColor.systemRedColor(), NSRange(0, 6))
    ctx_delete.setAttributedTitle_(delete_attr)
    ctx_menu.addItem_(ctx_delete)
    table.setMenu_(ctx_menu)

    scroll.setDocumentView_(table)
    view.addSubview_(scroll)

    return view


def _build_usage_pane(w: int, h: int) -> NSView:
    """Build the usage statistics pane."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    y = h - _PAD - 10

    title = NSTextField.labelWithString_("Usage")
    title.setFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, 24))
    title.setFont_(NSFont.boldSystemFontOfSize_(16.0))
    view.addSubview_(title)

    y -= 12
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, 1))
    sep.setBoxType_(2)
    view.addSubview_(sep)

    y -= 28

    history = get_history_service().get_all()
    usage_svc = get_usage_service()

    total_tokens: dict[str, int] = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
    for entry in history:
        tokens = usage_svc.get_tokens(entry.cwd)
        for k in total_tokens:
            total_tokens[k] += tokens[k]

    lines = format_tokens_breakdown(total_tokens)
    if not lines:
        lines = ["No usage data yet"]

    for line in lines:
        label = NSTextField.labelWithString_(line)
        label.setFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, 18))
        label.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(13.0, 0))
        label.setTextColor_(NSColor.secondaryLabelColor())
        view.addSubview_(label)
        y -= 22

    return view


def _build_about_pane(delegate: _PrefsDelegate, w: int, h: int) -> NSView:
    """Build the about pane."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    y = h - _PAD - 10

    title = NSTextField.labelWithString_("About")
    title.setFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, 24))
    title.setFont_(NSFont.boldSystemFontOfSize_(16.0))
    view.addSubview_(title)

    y -= 12
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, 1))
    sep.setBoxType_(2)
    view.addSubview_(sep)

    y -= 28
    ver_label = NSTextField.labelWithString_(f"ClaudeWatch v{__version__}")
    ver_label.setFrame_(NSMakeRect(_PAD, y, 300, 20))
    ver_label.setFont_(NSFont.systemFontOfSize_(13.0))
    view.addSubview_(ver_label)

    y -= 36
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

    return view


# ── Sidebar builder ──────────────────────────────────────────────────


def _build_sidebar(delegate: _PrefsDelegate) -> NSView:
    """Build the sidebar list."""
    sidebar = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _SIDEBAR_W, _H))
    sidebar.setWantsLayer_(True)

    items = delegate._sidebar_items
    y = _H - 12

    for i, item in enumerate(items):
        if item["type"] == "separator":
            y -= 8
            sep = NSBox.alloc().initWithFrame_(NSMakeRect(12, y, _SIDEBAR_W - 24, 1))
            sep.setBoxType_(2)
            sidebar.addSubview_(sep)
            y -= 8
            continue

        btn = NSButton.alloc().initWithFrame_(NSMakeRect(8, y - 28, _SIDEBAR_W - 16, 28))
        btn.setTitle_(item["label"])
        btn.setBezelStyle_(0)  # inline
        btn.setBordered_(False)
        btn.setFont_(NSFont.systemFontOfSize_(13.0))
        btn.setAlignment_(0)  # left
        btn.setTag_(i)
        btn.setTarget_(delegate)
        btn.setAction_(objc.selector(delegate.sidebarClicked_, signature=b"v@:@"))
        sidebar.addSubview_(btn)
        y -= 30

    # Vertical separator on the right edge
    vsep = NSBox.alloc().initWithFrame_(NSMakeRect(_SIDEBAR_W - 1, 0, 1, _H))
    vsep.setBoxType_(2)
    sidebar.addSubview_(vsep)

    return sidebar


# ── Public API ───────────────────────────────────────────────────────


def show_preferences() -> None:
    """Show (or bring to front) the preferences window."""
    global _window, _delegate  # noqa: PLW0603

    if _window is not None:
        _window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        return

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    _delegate = _PrefsDelegate.alloc().init()
    _delegate._sidebar_items = _sidebar_items()
    _delegate._feature_controls = {}
    _delegate._current_pane = None

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

    # Sidebar
    sidebar = _build_sidebar(_delegate)
    root.addSubview_(sidebar)

    # Content area
    content = NSView.alloc().initWithFrame_(NSMakeRect(_SIDEBAR_W, 0, _CONTENT_W, _H))
    root.addSubview_(content)
    _delegate._content_area = content

    # Show first item by default
    first_item = next((i for i in _delegate._sidebar_items if i["type"] != "separator"), None)
    if first_item:
        _delegate._show_pane(first_item)

    _window = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
