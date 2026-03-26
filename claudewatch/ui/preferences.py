"""Sidebar preferences window — macOS System Settings style."""

import os
import re
import subprocess
import webbrowser
from datetime import UTC, datetime, timedelta

import objc
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBox,
    NSButton,
    NSColor,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSMenuItem,
    NSMutableAttributedString,
    NSPasteboard,
    NSPasteboardTypeString,
    NSPopUpButton,
    NSSound,
    NSSwitch,
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
from claudewatch.backend.bookmark.dependencies import get_bookmark_service
from claudewatch.backend.core import features
from claudewatch.backend.core.helpers import escape_applescript, run_applescript
from claudewatch.backend.core.models import HostApp
from claudewatch.backend.core.paths import LOG_PATH
from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.summary.dependencies import get_summary_service
from claudewatch.backend.usage.dependencies import get_usage_service
from claudewatch.backend.usage.service import MODEL_DISPLAY_NAMES, format_tokens_compact
from claudewatch.ui.activity import show_activity
from claudewatch.ui.icons import get_app_icon

_REPO_URL = "https://github.com/wingatethomas/claudewatch"

# Layout
_W = 660
_H = 460
_SIDEBAR_W = 170
_CONTENT_W = _W - _SIDEBAR_W
_PAD = 24
_CARD_PAD = 16  # padding inside grouped cards
_CARD_RADIUS = 10.0
_ROW_H = 36  # sidebar row height

_window: NSWindow | None = None
_delegate: "_PrefsDelegate | None" = None
_history_data: list[dict] = []


# ── Sidebar items ────────────────────────────────────────────────────


def _sidebar_items() -> list[dict]:
    """Build sidebar item list."""
    return [
        {"type": "static", "key": "general", "label": "General"},
        {"type": "static", "key": "history", "label": "History"},
        {"type": "separator"},
        {"type": "static", "key": "about", "label": "About"},
    ]


# ── UI helpers ───────────────────────────────────────────────────────


def _make_card(x: float, y: float, w: float, h: float) -> NSBox:
    """Create a rounded-rect grouped container like macOS Settings cards."""
    card = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    card.setBoxType_(4)  # NSBoxCustom
    card.setBorderType_(1)  # NSLineBorder
    card.setCornerRadius_(_CARD_RADIUS)
    card.setFillColor_(NSColor.windowBackgroundColor().blendedColorWithFraction_ofColor_(0.06, NSColor.whiteColor()))
    card.setBorderColor_(NSColor.separatorColor().colorWithAlphaComponent_(0.3))
    card.setTitlePosition_(0)  # NSNoTitle
    card.setContentViewMargins_((0, 0))
    return card


def _make_label(text: str, x: float, y: float, w: float, size: float = 13.0, bold: bool = False) -> NSTextField:  # noqa: PLR0913
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(x, y, w, 18))
    label.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    return label


def _make_secondary_label(text: str, x: float, y: float, w: float, size: float = 12.0) -> NSTextField:
    label = _make_label(text, x, y, w, size)
    label.setTextColor_(NSColor.secondaryLabelColor())
    return label


# ── Delegate ─────────────────────────────────────────────────────────


class _PrefsDelegate(NSObject):  # noqa: PLR0904
    """Handles sidebar selection, feature toggles, facets, and history table."""

    _sidebar_items: list[dict]
    _sidebar_btns: list[NSButton]
    _content_area: NSView | None
    _current_pane: NSView | None
    _feature_controls: dict
    _selected_idx: int

    def _show_pane(self, item: dict) -> None:
        if self._current_pane is not None:
            self._current_pane.removeFromSuperview()
            self._current_pane = None

        content_h = _H
        if item["key"] == "general":
            pane = _build_general_pane(self, _CONTENT_W, content_h)
        elif item["key"] == "history":
            pane = _build_history_pane(self, _CONTENT_W, content_h)
        elif item["key"] == "about":
            pane = _build_about_pane(self, _CONTENT_W, content_h)
        else:
            return

        pane.setFrame_(NSMakeRect(0, 0, _CONTENT_W, content_h))
        self._content_area.addSubview_(pane)
        self._current_pane = pane

    def _select_sidebar(self, idx: int) -> None:
        """Update sidebar selection highlight and show the corresponding pane."""
        # Un-highlight previous
        if hasattr(self, "_selected_idx") and 0 <= self._selected_idx < len(self._sidebar_btns):
            old_btn = self._sidebar_btns[self._selected_idx]
            if old_btn is not None:
                old_btn.wantsLayer()  # ensure layer exists
                old_btn.layer().setBackgroundColor_(NSColor.clearColor().CGColor())

        self._selected_idx = idx

        # Highlight new
        if 0 <= idx < len(self._sidebar_btns):
            btn = self._sidebar_btns[idx]
            if btn is not None:
                btn.wantsLayer()
                btn.layer().setBackgroundColor_(NSColor.controlAccentColor().colorWithAlphaComponent_(0.18).CGColor())

        if 0 <= idx < len(self._sidebar_items):
            item = self._sidebar_items[idx]
            if item["type"] != "separator":
                self._show_pane(item)

    # ── Sidebar click ──

    def sidebarClicked_(self, sender: objc.objc_object) -> None:  # noqa: N802
        tag = sender.tag()
        if tag < 0 or tag >= len(self._sidebar_items):
            return
        item = self._sidebar_items[tag]
        if item["type"] != "separator":
            self._select_sidebar(tag)

    # ── Feature actions ──

    def featureToggled_(self, sender: objc.objc_object) -> None:  # noqa: N802
        key = str(sender.representedObject() or "")
        if not key:
            key = str(sender.cell().representedObject())
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

    # ── History card actions ──

    def copyCwd_(self, sender: objc.objc_object) -> None:  # noqa: N802
        cwd = str(sender.representedObject())
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(cwd, NSPasteboardTypeString)

    def revealInFinder_(self, sender: objc.objc_object) -> None:  # noqa: N802
        cwd = str(sender.representedObject())
        if os.path.isdir(cwd):
            subprocess.run(["open", cwd], check=False)  # noqa: S603, S607

    # ── Danger zone ──

    def clearBookmarks_(self, sender: objc.objc_object) -> None:  # noqa: N802
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Delete all bookmarks?")
        alert.setInformativeText_("This will remove all pinned sessions. This cannot be undone.")
        alert.addButtonWithTitle_("Delete All")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() == NSAlertFirstButtonReturn:
            get_bookmark_service().clear_all()

    def clearSummaries_(self, sender: objc.objc_object) -> None:  # noqa: N802
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Delete all summaries?")
        alert.setInformativeText_("Cached summaries will be regenerated as needed. This cannot be undone.")
        alert.addButtonWithTitle_("Delete All")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() == NSAlertFirstButtonReturn:
            get_summary_service().clear_all()

    # ── Static actions ──

    def viewAuditLog_(self, sender: objc.objc_object) -> None:  # noqa: N802
        if os.path.exists(LOG_PATH):
            subprocess.run(["open", "-a", "Console", LOG_PATH], check=False)  # noqa: S603, S607

    def openRepo_(self, sender: objc.objc_object) -> None:  # noqa: N802
        webbrowser.open(_REPO_URL)

    # ── History ──

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
        if entry:
            sender.setRepresentedObject_(f"{entry.get('session_id', '')}|{entry.get('cwd', '')}")
            self.resumeSession_(sender)

    def activitySelected_(self, sender: objc.objc_object) -> None:  # noqa: N802
        entry = self._selected_entry()
        if entry:
            sender.setRepresentedObject_(f"{entry.get('project', '')}|{entry.get('cwd', '')}")
            self.viewActivity_(sender)

    def deleteSelected_(self, sender: objc.objc_object) -> None:  # noqa: N802
        entry = self._selected_entry()
        if entry:
            sender.setRepresentedObject_(entry.get("cwd", ""))
            self.deleteHistoryEntry_(sender)

    def windowWillClose_(self, notification: objc.objc_object) -> None:  # noqa: N802
        global _window  # noqa: PLW0603
        _window = None


# ── Helpers ──────────────────────────────────────────────────────────


def _relative_time(iso_str: str) -> str:  # noqa: PLR0911
    """Convert ISO timestamp to relative time: '2h ago', 'yesterday', 'Mar 23'."""
    try:
        dt = datetime.fromisoformat(iso_str)
        now = datetime.now(tz=UTC)
        delta = now - dt
        if delta < timedelta(minutes=1):
            return "just now"
        if delta < timedelta(hours=1):
            m = int(delta.total_seconds() / 60)
            return f"{m}m ago"
        if delta < timedelta(hours=24):
            h = int(delta.total_seconds() / 3600)
            return f"{h}h ago"
        if delta < timedelta(days=2):
            return "yesterday"
        if delta < timedelta(days=7):
            d = int(delta.days)
            return f"{d}d ago"
        return dt.strftime("%b %-d")
    except (ValueError, TypeError):
        return ""


def _reload_history_data() -> None:
    global _history_data  # noqa: PLW0603
    _history_data = [e.to_dict() for e in get_history_service().get_all()]


# ── Content pane builders ────────────────────────────────────────────


def _add_feature_card(  # noqa: PLR0913, PLR0915
    view: NSView,
    delegate: _PrefsDelegate,
    feature: features.Feature,
    card_x: float,
    card_y: float,
    card_w: float,
) -> None:
    """Add a single feature card with toggle row + facet rows."""
    feature_key = feature.key
    enabled = features.is_enabled(feature_key)

    _toggle_row_h = 44
    _facet_row_h = 40
    card_h = _toggle_row_h + len(feature.facets) * _facet_row_h

    card = _make_card(card_x, card_y, card_w, card_h)
    view.addSubview_(card)
    content = card.contentView()

    # Toggle row
    row_y = card_h - _toggle_row_h
    name_label = _make_label(feature.description, _CARD_PAD, row_y + 12, card_w - _CARD_PAD * 2 - 60, 13.0)
    content.addSubview_(name_label)

    toggle = NSSwitch.alloc().initWithFrame_(NSMakeRect(card_w - _CARD_PAD - 46, row_y + 10, 46, 22))
    toggle.setState_(NSControlStateValueOn if enabled else NSControlStateValueOff)
    toggle.setRepresentedObject_(feature_key)
    toggle.setTarget_(delegate)
    toggle.setAction_(objc.selector(delegate.featureToggled_, signature=b"v@:@"))
    content.addSubview_(toggle)

    # Facet rows
    facet_controls: list[objc.objc_object] = []
    for i, facet in enumerate(feature.facets):
        fy = row_y - (i + 1) * _facet_row_h

        sep = NSBox.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, fy + _facet_row_h - 1, card_w - _CARD_PAD * 2, 1))
        sep.setBoxType_(2)
        content.addSubview_(sep)

        facet_label = facet.description or facet.name.replace("_", " ").title()
        label = _make_label(facet_label, _CARD_PAD, fy + 11, 140, 12.0)
        label.setTextColor_(NSColor.secondaryLabelColor())
        content.addSubview_(label)

        if facet.type == "choice":
            _popup_w = 160
            popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(card_w - _CARD_PAD - _popup_w, fy + 8, _popup_w, 24),
                False,
            )
            popup.setFont_(NSFont.systemFontOfSize_(12.0))
            popup.addItemsWithTitles_(list(facet.options))
            current = features.get_facet(feature_key, facet.name)
            if current is not None:
                popup.selectItemWithTitle_(str(current))
            popup.cell().setRepresentedObject_(f"{feature_key}|{facet.name}")
            popup.setTarget_(delegate)
            popup.setAction_(objc.selector(delegate.facetChanged_, signature=b"v@:@"))
            popup.setEnabled_(enabled)
            content.addSubview_(popup)
            facet_controls.append(popup)

    delegate._feature_controls[feature_key] = facet_controls


def _build_general_pane(delegate: _PrefsDelegate, w: int, h: int) -> NSView:  # noqa: PLR0915
    """Build the General pane — all features as stacked cards."""
    delegate._feature_controls = {}
    all_features = features.get_all()

    _toggle_row_h = 44
    _facet_row_h = 40
    _card_gap = 12

    _danger_row_h = 40
    _danger_header_h = 32  # "Danger Zone" label row inside card
    _danger_rows = 2
    _danger_h = _danger_header_h + _danger_row_h * _danger_rows
    _danger_gap = 20

    # Calculate total height needed
    total_h = _PAD
    for f in all_features:
        total_h += _toggle_row_h + len(f.facets) * _facet_row_h + _card_gap
    total_h += _danger_gap + _danger_h + _PAD
    inner_h = max(h, total_h)

    inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, inner_h))
    card_w = w - _PAD * 2

    y = inner_h - _PAD
    for feature in all_features:
        card_h = _toggle_row_h + len(feature.facets) * _facet_row_h
        y -= card_h
        _add_feature_card(inner, delegate, feature, _PAD, y, card_w)
        y -= _card_gap

    # Danger zone
    y -= _danger_gap - _card_gap  # extra space before danger zone

    danger_card = _make_card(_PAD, y - _danger_h, card_w, _danger_h)
    danger_card.setBorderColor_(NSColor.systemRedColor().colorWithAlphaComponent_(0.3))
    inner.addSubview_(danger_card)
    dc = danger_card.contentView()

    # Header row inside card
    header_y = _danger_h - _danger_header_h
    danger_label = _make_label("Danger Zone", _CARD_PAD, header_y + 7, 200, 11.0)
    danger_label.setTextColor_(NSColor.systemRedColor().colorWithAlphaComponent_(0.8))
    danger_label.setFont_(NSFont.boldSystemFontOfSize_(11.0))
    dc.addSubview_(danger_label)

    header_sep = NSBox.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, header_y - 1, card_w - _CARD_PAD * 2, 1))
    header_sep.setBoxType_(2)
    dc.addSubview_(header_sep)

    _btn_w = 80
    _btn_h = 22

    # Row 1: Clear Bookmarks
    row1_y = header_y - _danger_row_h
    label1 = _make_label("Clear all bookmarks", _CARD_PAD, row1_y + 10, card_w - _CARD_PAD * 2 - _btn_w - 8, 12.0)
    dc.addSubview_(label1)
    bm_btn = NSButton.alloc().initWithFrame_(NSMakeRect(card_w - _CARD_PAD - _btn_w, row1_y + 8, _btn_w, _btn_h))
    bm_btn.setTitle_("Clear...")
    bm_btn.setBezelStyle_(1)
    bm_btn.setFont_(NSFont.systemFontOfSize_(11.0))
    bm_btn.setTarget_(delegate)
    bm_btn.setAction_(objc.selector(delegate.clearBookmarks_, signature=b"v@:@"))
    dc.addSubview_(bm_btn)

    row_sep = NSBox.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, row1_y - 1, card_w - _CARD_PAD * 2, 1))
    row_sep.setBoxType_(2)
    dc.addSubview_(row_sep)

    # Row 2: Clear Summaries
    row2_y = row1_y - _danger_row_h
    label2 = _make_label("Clear all summaries", _CARD_PAD, row2_y + 10, card_w - _CARD_PAD * 2 - _btn_w - 8, 12.0)
    dc.addSubview_(label2)
    sum_btn = NSButton.alloc().initWithFrame_(NSMakeRect(card_w - _CARD_PAD - _btn_w, row2_y + 8, _btn_w, _btn_h))
    sum_btn.setTitle_("Clear...")
    sum_btn.setBezelStyle_(1)
    sum_btn.setFont_(NSFont.systemFontOfSize_(11.0))
    sum_btn.setTarget_(delegate)
    sum_btn.setAction_(objc.selector(delegate.clearSummaries_, signature=b"v@:@"))
    dc.addSubview_(sum_btn)

    # Wrap in scroll view if needed
    if inner_h <= h:
        return inner

    scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)
    scroll.setDocumentView_(inner)
    return scroll


def _build_history_pane(delegate: _PrefsDelegate, w: int, h: int) -> NSView:  # noqa: PLR0915
    """Build the history pane as session cards."""
    _reload_history_data()

    if not _history_data:
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        empty = _make_secondary_label("No session history yet.", _PAD, h // 2, w - _PAD * 2, 13.0)
        empty.setAlignment_(1)
        view.addSubview_(empty)
        return view

    _card_h = 72
    _card_gap = 8
    card_w = w - _PAD * 2

    total_h = _PAD + len(_history_data) * (_card_h + _card_gap) + _PAD
    inner_h = max(h, total_h)
    inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, inner_h))

    pinned_cwds = get_bookmark_service().get_pinned_cwds()
    usage_svc = get_usage_service()
    summary_svc = get_summary_service()

    y = inner_h - _PAD
    for entry in _history_data:
        y -= _card_h
        _add_history_card(inner, delegate, entry, _PAD, y, card_w, _card_h, pinned_cwds, usage_svc, summary_svc)
        y -= _card_gap

    scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)
    scroll.setDocumentView_(inner)
    # Scroll to top
    inner.scrollPoint_((0, inner_h))
    return scroll


def _add_history_card(  # noqa: PLR0913, PLR0915
    view: NSView,
    delegate: _PrefsDelegate,
    entry: dict,
    x: float,
    y: float,
    w: float,
    h: float,
    pinned_cwds: set[str],
    usage_svc: object,
    summary_svc: object,
) -> None:
    """Add a compact session history card."""
    card = _make_card(x, y, w, h)
    view.addSubview_(card)
    c = card.contentView()

    project = entry.get("project", "unknown")
    cwd = entry.get("cwd", "")
    session_id = entry.get("session_id", "")
    model_raw = entry.get("model", "")
    model = MODEL_DISPLAY_NAMES.get(model_raw, model_raw)
    host_app_str = entry.get("host_app", "Terminal")
    ended_at = entry.get("ended_at", "")
    is_pinned = cwd in pinned_cwds
    _p = _CARD_PAD  # shorthand

    # ── Line 1: [icon] project                   model ★
    ly1 = h - 22
    app_enum = next((ha for ha in HostApp if ha.value == host_app_str), HostApp.TERMINAL)
    icon = get_app_icon(app_enum, size=14)
    name_x = _p
    if icon:
        iv = NSButton.alloc().initWithFrame_(NSMakeRect(_p, ly1 + 1, 14, 14))
        iv.setImage_(icon)
        iv.setBordered_(False)
        iv.setEnabled_(False)
        c.addSubview_(iv)
        name_x = _p + 20

    name_label = _make_label(project, name_x, ly1 - 1, w - name_x - 70, 12.0, bold=True)
    c.addSubview_(name_label)

    right_text = model + ("  \u2605" if is_pinned else "")
    model_label = _make_secondary_label(right_text, w - _p - 60, ly1, 60, 10.0)
    model_label.setAlignment_(2)  # right
    c.addSubview_(model_label)

    # ── Line 2: time · tokens (or just time)
    ly2 = ly1 - 16
    time_str = _relative_time(ended_at)
    tokens = usage_svc.get_tokens(cwd) if cwd else {}
    token_str = format_tokens_compact(tokens) if tokens else ""
    meta = time_str
    if token_str:
        meta += f"  ·  {token_str}"
    meta_label = _make_secondary_label(meta, _p, ly2, w - _p * 2, 10.0)
    meta_label.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(10.0, 0))
    c.addSubview_(meta_label)

    # ── Line 3: summary (if available) or skip
    ly3 = ly2 - 14
    summary = summary_svc.get_cached(cwd) if cwd else None
    _max_summary = 65
    if summary:
        s_text = summary[:_max_summary] + "…" if len(summary) > _max_summary else summary
        s_label = _make_secondary_label(s_text, _p, ly3, w - _p * 2, 10.0)
        s_label.setTextColor_(NSColor.tertiaryLabelColor())
        c.addSubview_(s_label)

    # ── Bottom row: actions right-aligned
    _btn_h = 18
    _btn_font = NSFont.systemFontOfSize_(10.0)
    btn_y = 6
    btn_x = w - _p

    # ··· meatball (rightmost)
    btn_x -= 28
    meatball = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(btn_x, btn_y, 28, _btn_h), True)
    meatball.setFont_(_btn_font)
    meatball.setBordered_(False)
    meatball.addItemWithTitle_("···")
    meatball.itemAtIndex_(0).setTitle_("···")

    for title, action, obj in [
        ("Copy Path", delegate.copyCwd_, cwd),
        ("Open in Finder", delegate.revealInFinder_, cwd),
    ]:
        meatball.addItemWithTitle_(title)
        idx = meatball.numberOfItems() - 1
        meatball.itemAtIndex_(idx).setRepresentedObject_(obj)
        meatball.itemAtIndex_(idx).setTarget_(delegate)
        meatball.itemAtIndex_(idx).setAction_(objc.selector(action, signature=b"v@:@"))

    meatball.menu().addItem_(NSMenuItem.separatorItem())
    meatball.addItemWithTitle_("Delete")
    d_idx = meatball.numberOfItems() - 1
    meatball.itemAtIndex_(d_idx).setRepresentedObject_(cwd)
    meatball.itemAtIndex_(d_idx).setTarget_(delegate)
    meatball.itemAtIndex_(d_idx).setAction_(objc.selector(delegate.deleteHistoryEntry_, signature=b"v@:@"))
    d_attr = NSMutableAttributedString.alloc().initWithString_("Delete")
    d_attr.addAttribute_value_range_("NSColor", NSColor.systemRedColor(), NSRange(0, 6))
    meatball.itemAtIndex_(d_idx).setAttributedTitle_(d_attr)
    c.addSubview_(meatball)

    # Activity
    btn_x -= 52
    act_btn = NSButton.alloc().initWithFrame_(NSMakeRect(btn_x, btn_y, 50, _btn_h))
    act_btn.setTitle_("Activity")
    act_btn.setBezelStyle_(1)
    act_btn.setFont_(_btn_font)
    act_btn.setRepresentedObject_(f"{project}|{cwd}")
    act_btn.setTarget_(delegate)
    act_btn.setAction_(objc.selector(delegate.viewActivity_, signature=b"v@:@"))
    c.addSubview_(act_btn)

    # Resume
    if session_id:
        btn_x -= 54
        res_btn = NSButton.alloc().initWithFrame_(NSMakeRect(btn_x, btn_y, 50, _btn_h))
        res_btn.setTitle_("Resume")
        res_btn.setBezelStyle_(1)
        res_btn.setFont_(_btn_font)
        res_btn.setRepresentedObject_(f"{session_id}|{cwd}")
        res_btn.setTarget_(delegate)
        res_btn.setAction_(objc.selector(delegate.resumeSession_, signature=b"v@:@"))
        c.addSubview_(res_btn)


def _build_about_pane(delegate: _PrefsDelegate, w: int, h: int) -> NSView:
    """Build the about pane with a grouped card."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))

    card_h = 100
    card_w = w - _PAD * 2
    card = _make_card(_PAD, h - _PAD - card_h, card_w, card_h)
    view.addSubview_(card)
    content = card.contentView()

    ver_label = _make_label(f"ClaudeWatch v{__version__}", _CARD_PAD, card_h - _CARD_PAD - 20, 300, 14.0, bold=True)
    content.addSubview_(ver_label)

    btn_y = _CARD_PAD
    log_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, btn_y, 100, 28))
    log_btn.setTitle_("Audit Log")
    log_btn.setBezelStyle_(1)
    log_btn.setTarget_(delegate)
    log_btn.setAction_(objc.selector(delegate.viewAuditLog_, signature=b"v@:@"))
    content.addSubview_(log_btn)

    repo_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_CARD_PAD + 112, btn_y, 80, 28))
    repo_btn.setTitle_("GitHub")
    repo_btn.setBezelStyle_(1)
    repo_btn.setTarget_(delegate)
    repo_btn.setAction_(objc.selector(delegate.openRepo_, signature=b"v@:@"))
    content.addSubview_(repo_btn)

    return view


# ── Sidebar builder ──────────────────────────────────────────────────


def _build_sidebar(delegate: _PrefsDelegate) -> NSView:
    """Build the sidebar with selection-highlighted rows."""
    sidebar = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _SIDEBAR_W, _H))
    sidebar.setWantsLayer_(True)
    sidebar.layer().setBackgroundColor_(
        NSColor.windowBackgroundColor().blendedColorWithFraction_ofColor_(0.03, NSColor.blackColor()).CGColor()
    )

    items = delegate._sidebar_items
    btns: list[NSButton] = []
    y = _H - 8

    for i, item in enumerate(items):
        if item["type"] == "separator":
            y -= 6
            sep = NSBox.alloc().initWithFrame_(NSMakeRect(12, y, _SIDEBAR_W - 24, 1))
            sep.setBoxType_(2)
            sidebar.addSubview_(sep)
            y -= 6
            btns.append(None)  # placeholder to keep indices aligned
            continue

        btn_h = _ROW_H - 4
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(8, y - btn_h, _SIDEBAR_W - 16, btn_h))
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
        y -= _ROW_H

    # Vertical separator
    vsep = NSBox.alloc().initWithFrame_(NSMakeRect(_SIDEBAR_W - 1, 0, 1, _H))
    vsep.setBoxType_(2)
    sidebar.addSubview_(vsep)

    delegate._sidebar_btns = btns
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
    _delegate._selected_idx = -1

    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(200, 200, _W, _H),
        style,
        NSBackingStoreBuffered,
        False,
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

    # Select first non-separator item
    for i, item in enumerate(_delegate._sidebar_items):
        if item["type"] != "separator":
            _delegate._select_sidebar(i)
            break

    _window = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
