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
from claudewatch.backend.bookmark.dependencies import get_bookmark_service
from claudewatch.backend.core import features
from claudewatch.backend.core.helpers import escape_applescript, run_applescript
from claudewatch.backend.core.paths import LOG_PATH
from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.usage.dependencies import get_usage_service
from claudewatch.backend.usage.service import MODEL_DISPLAY_NAMES, format_tokens_breakdown
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
    _feature_controls: dict  # feature_key -> list of facet controls

    # ── Feature actions (generic) ──

    def featureToggled_(self, sender: objc.objc_object) -> None:
        key = str(sender.cell().representedObject())
        enabled = sender.state() == NSControlStateValueOn
        features.set_enabled(key, enabled)
        for ctrl in self._feature_controls.get(key, []):
            ctrl.setEnabled_(enabled)

    def facetChanged_(self, sender: objc.objc_object) -> None:
        info = str(sender.cell().representedObject())
        key, facet_name = info.split("|", 1)
        if hasattr(sender, "titleOfSelectedItem"):
            value: object = sender.titleOfSelectedItem()
        else:
            value = sender.state() == NSControlStateValueOn
        features.set_facet(key, facet_name, value)
        # Sound preview
        if key == "notifications" and facet_name == "sound":
            sound = NSSound.soundNamed_(value)
            if sound:
                sound.play()

    # ── Static actions ──

    def viewAuditLog_(self, sender: objc.objc_object) -> None:
        log_path = LOG_PATH
        if os.path.exists(log_path):
            subprocess.run(["open", "-a", "Console", log_path], check=False)  # noqa: S603, S607

    def openRepo_(self, sender: objc.objc_object) -> None:
        webbrowser.open(_REPO_URL)

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
            get_history_service().remove(cwd)
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
            pinned = entry.get("cwd", "") in get_bookmark_service().get_pinned_cwds()
            return f"{entry.get('project', 'unknown')}{'  \u2605' if pinned else ''}"
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

    # ── Table selection tracking ──

    _actions_popup: NSPopUpButton | None = None

    def tableViewSelectionDidChange_(self, notification: objc.objc_object) -> None:
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
    _history_data = [e.to_dict() for e in get_history_service().get_all()]


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

    # Bottom toolbar with Actions dropdown
    _bar_h = 36
    bar = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _bar_h))

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

    sep = NSBox.alloc().initWithFrame_(NSMakeRect(0, _bar_h - 1, _W, 1))
    sep.setBoxType_(2)
    bar.addSubview_(sep)
    view.addSubview_(bar)

    scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(0, _bar_h, _W, content_h - _bar_h))
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)

    table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, content_h - _bar_h))
    table.setUsesAlternatingRowBackgroundColors_(True)
    table.setRowHeight_(28)
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

    table.setColumnAutoresizingStyle_(1)  # NSTableViewUniformColumnAutoresizingStyle

    table.setDataSource_(delegate)
    table.setDelegate_(delegate)
    delegate._history_table = table
    delegate._actions_popup = actions_popup

    # Right-click context menu with the same actions as the dropdown
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


# ── Settings pane section builders ────────────────────────────────────


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


def _build_facet_control(  # noqa: PLR0913
    view: NSView,
    delegate: _PrefsDelegate,
    feature_key: str,
    facet: features.Facet,
    enabled: bool,
    y: float,
) -> tuple[objc.objc_object, float]:
    """Build the appropriate control for a facet. Returns (control, new_y)."""
    label = NSTextField.labelWithString_(facet.description or facet.name)
    label.setFrame_(NSMakeRect(_PAD, y, 120, 20))
    label.setFont_(NSFont.systemFontOfSize_(13.0))
    view.addSubview_(label)

    if facet.type == "choice":
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(_PAD + 130, y - 2, 200, 22),
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
        return popup, y

    if facet.type == "bool":
        checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD, y, _W - _PAD * 2, 20))
        checkbox.setButtonType_(NSButtonTypeSwitch)
        checkbox.setTitle_(facet.description or facet.name)
        checkbox.setFont_(NSFont.systemFontOfSize_(13.0))
        val = features.get_facet(feature_key, facet.name)
        checkbox.setState_(NSControlStateValueOn if val else NSControlStateValueOff)
        checkbox.cell().setRepresentedObject_(f"{feature_key}|{facet.name}")
        checkbox.setTarget_(delegate)
        checkbox.setAction_(objc.selector(delegate.facetChanged_, signature=b"v@:@"))
        checkbox.setEnabled_(enabled)
        view.addSubview_(checkbox)
        return checkbox, y

    return None, y


def _add_feature_section(
    view: NSView,
    delegate: _PrefsDelegate,
    feature: features.Feature,
    y: float,
) -> float:
    """Render a single feature with enable toggle and facet controls."""
    _add_section_header(view, feature.description.upper(), y)
    y -= 28

    enabled = features.is_enabled(feature.key)
    toggle = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD, y, _W - _PAD * 2, 20))
    toggle.setButtonType_(NSButtonTypeSwitch)
    toggle.setTitle_("Enabled")
    toggle.setFont_(NSFont.systemFontOfSize_(13.0))
    toggle.setState_(NSControlStateValueOn if enabled else NSControlStateValueOff)
    toggle.cell().setRepresentedObject_(feature.key)
    toggle.setTarget_(delegate)
    toggle.setAction_(objc.selector(delegate.featureToggled_, signature=b"v@:@"))
    view.addSubview_(toggle)

    facet_controls: list[objc.objc_object] = []
    for facet in feature.facets:
        y -= 30
        ctrl, y = _build_facet_control(view, delegate, feature.key, facet, enabled, y)
        if ctrl is not None:
            facet_controls.append(ctrl)

    delegate._feature_controls[feature.key] = facet_controls
    return y


def _add_usage_section(view: NSView, y: float) -> float:
    """Render inline usage statistics aggregated from history."""
    _add_section_separator(view, y + 10)
    _add_section_header(view, "USAGE", y - 10)
    y -= 34

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
        label.setFrame_(NSMakeRect(_PAD, y, _W - _PAD * 2, 16))
        label.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(12.0, 0))
        label.setTextColor_(NSColor.secondaryLabelColor())
        view.addSubview_(label)
        y -= 18

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
    """Build the Settings pane with dynamic feature sections, usage, and about."""
    content_h = _H - _TOOLBAR_H
    delegate._feature_controls = {}

    all_features = features.get_all()
    num_facets = sum(len(f.facets) for f in all_features)
    # Estimate content height: per feature ~60px + per facet ~30px + usage ~100px + about ~80px + padding
    est_height = len(all_features) * 60 + num_facets * 30 + 220 + _PAD * 2
    inner_h = max(content_h, est_height)

    inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, inner_h))

    y = inner_h - _PAD

    # Dynamic feature sections
    for i, feature in enumerate(all_features):
        if i > 0:
            y -= 20
            _add_section_separator(inner, y + 10)
        y = _add_feature_section(inner, delegate, feature, y)

    # Usage
    y -= 30
    y = _add_usage_section(inner, y)

    # About
    y -= 30
    y = _add_about_section(inner, delegate, y)

    if inner_h <= content_h:
        return inner

    scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, content_h))
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)
    scroll.setDocumentView_(inner)
    return scroll


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

    # Toolbar: segmented control for Preferences / History
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
