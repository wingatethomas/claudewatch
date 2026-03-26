"""Sidebar preferences window — macOS System Settings style."""

import os
import re
import subprocess
import time
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
    NSMenu,
    NSMenuItem,
    NSMutableAttributedString,
    NSPasteboard,
    NSPasteboardTypeString,
    NSPopUpButton,
    NSSearchField,
    NSSegmentedControl,
    NSSegmentStyleTexturedRounded,
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
from claudewatch.backend.core.features import FacetType
from claudewatch.backend.core.helpers import escape_applescript, run_applescript
from claudewatch.backend.core.paths import LOG_PATH
from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.summary.dependencies import get_summary_service
from claudewatch.backend.usage.dependencies import get_usage_service
from claudewatch.backend.usage.service import MODEL_DISPLAY_NAMES, format_tokens_compact
from claudewatch.ui.activity import show_activity
from claudewatch.ui.icons import sf_icon

_REPO_URL = "https://github.com/wingatethomas/claudewatch"

# Layout
_W = 660
_H = 620
_SIDEBAR_W = 170
_CONTENT_W = _W - _SIDEBAR_W
_PAD = 24
_CARD_PAD = 16  # padding inside grouped cards
_CARD_RADIUS = 10.0
_ROW_H = 36  # sidebar row height

_window: NSWindow | None = None
_delegate: "_PrefsDelegate | None" = None
_history_data: list[dict] = []

# Sub-descriptions for feature toggles
_FEATURE_DETAILS: dict[str, str] = {
    "bookmarks": "Pin sessions to resume later from the menu bar.",
    "notifications": "Get alerts when Claude needs your attention.",
    "background_summaries": "Periodically regenerate session summaries in the background.",
    "auto_updates": "Check GitHub for new releases periodically.",
}


# ── Sidebar items ────────────────────────────────────────────────────


def _sidebar_items() -> list[dict]:
    """Build sidebar item list."""
    return [
        {"type": "static", "key": "general", "label": "General"},
        {"type": "static", "key": "history", "label": "History"},
        {"type": "static", "key": "usage", "label": "Usage"},
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


def _add_pane_header(view: NSView, title: str, w: float, h: float) -> float:
    """Add a large title header to a content pane. Returns y below the header.

    Places header 12px below the top of the view (h). NSView is bottom-up,
    so label bottom = h - 36, label top = h - 12.
    """
    _header_label_h = 24
    _top_inset = 12
    y = h - _top_inset - _header_label_h
    label = NSTextField.labelWithString_(title)
    label.setFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, _header_label_h))
    label.setFont_(NSFont.boldSystemFontOfSize_(18.0))
    view.addSubview_(label)
    return y - 8  # 8px gap below header


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

    # History filter state
    _history_search: str
    _history_sort: str  # "date" or "name"
    _history_sort_asc: bool
    _history_bookmarked_only: bool
    _history_scroll: AppKitScrollView | None
    _history_inner: NSView | None
    _history_sort_seg: NSSegmentedControl | None

    def _show_pane(self, item: dict) -> None:
        if self._current_pane is not None:
            self._current_pane.removeFromSuperview()
            self._current_pane = None

        content_h = _H
        if item["key"] == "general":
            pane = _build_general_pane(self, _CONTENT_W, content_h)
        elif item["key"] == "history":
            pane = _build_history_pane(self, _CONTENT_W, content_h)
        elif item["key"] == "usage":
            pane = _build_usage_pane(self, _CONTENT_W, content_h)
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

    # ── History filter actions ──

    def historySearchChanged_(self, sender: objc.objc_object) -> None:  # noqa: N802
        self._history_search = str(sender.stringValue()).strip().lower()
        _rebuild_history_rows(self)

    def historySortChanged_(self, sender: objc.objc_object) -> None:  # noqa: N802
        idx = sender.selectedSegment()
        new_sort = "name" if idx == 1 else "date"
        if new_sort == self._history_sort:
            # Same segment clicked again — toggle direction
            self._history_sort_asc = not self._history_sort_asc
        else:
            self._history_sort = new_sort
            self._history_sort_asc = new_sort == "name"  # name defaults asc, date defaults desc
        # Update label to show direction
        arrow_up = " ↑"
        arrow_down = " ↓"
        for i, base in enumerate(("Date", "Name")):
            if i == idx:
                arrow = arrow_up if self._history_sort_asc else arrow_down
                sender.setLabel_forSegment_(base + arrow, i)
            else:
                sender.setLabel_forSegment_(base, i)
        _rebuild_history_rows(self)

    def historyBookmarkFilter_(self, sender: objc.objc_object) -> None:  # noqa: N802
        self._history_bookmarked_only = sender.state() == NSControlStateValueOn
        _rebuild_history_rows(self)

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

    # ── Row menu ──

    def showRowMenu_(self, sender: objc.objc_object) -> None:  # noqa: N802
        menu = sender.menu()
        if menu:
            NSMenu.popUpContextMenu_withEvent_forView_(
                menu,
                NSApplication.sharedApplication().currentEvent(),
                sender,
            )

    # ── Navigation ──

    def jumpToSession_(self, sender: objc.objc_object) -> None:  # noqa: N802
        """Switch to History pane filtered to the given project name."""
        project = str(sender.representedObject())
        self._history_search = project.lower()
        self._history_sort = getattr(self, "_history_sort", "date")
        self._history_sort_asc = getattr(self, "_history_sort_asc", False)
        self._history_bookmarked_only = False
        # Find and select the History sidebar item
        for i, item in enumerate(self._sidebar_items):
            if item.get("key") == "history":
                self._select_sidebar(i)
                break

    # ── Bookmark actions ──

    def bookmarkSession_(self, sender: objc.objc_object) -> None:  # noqa: N802
        data = str(sender.representedObject())
        if "|" not in data:
            return
        sid, rest = data.split("|", 1)
        project, cwd = rest.split("|", 1) if "|" in rest else ("", rest)
        get_bookmark_service().add(sid, project, cwd, "")

    def unbookmarkSession_(self, sender: objc.objc_object) -> None:  # noqa: N802
        cwd = str(sender.representedObject())
        get_bookmark_service().remove(cwd)

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

    def facetBoolChanged_(self, sender: objc.objc_object) -> None:  # noqa: N802
        info = str(sender.representedObject())
        key, facet_name = info.split("|", 1)
        value = sender.state() == NSControlStateValueOn
        features.set_facet(key, facet_name, value)

    # ── Static actions ──

    def openClaudeUsage_(self, sender: objc.objc_object) -> None:  # noqa: N802
        """Open claude /usage in Terminal using a known trusted directory."""
        # Find a trusted CWD from history
        history = get_history_service().get_all()
        cwd = ""
        for entry in history:
            if entry.cwd and os.path.isdir(entry.cwd):
                cwd = entry.cwd
                break
        if not cwd:
            cwd = os.path.expanduser("~")
        safe_cwd = escape_applescript(cwd)
        run_applescript(f'''
            tell application "Terminal"
                activate
                do script "cd \\"{safe_cwd}\\" && claude /usage"
            end tell
        ''')

    def openAnthropicConsole_(self, sender: objc.objc_object) -> None:  # noqa: N802
        webbrowser.open("https://console.anthropic.com/settings/usage")

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
            pinned = entry.get("cwd", "") in get_bookmark_service().get_bookmarked_cwds()
            return f"{entry.get('project', 'unknown')}{'  \u25b8' if pinned else ''}"
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
    """Add a single feature card with toggle row + sub-description + facet rows."""
    feature_key = feature.key
    enabled = features.is_enabled(feature_key)
    detail = _FEATURE_DETAILS.get(feature_key, "")

    _toggle_row_h = 56 if detail else 44
    _facet_row_h = 40
    card_h = _toggle_row_h + len(feature.facets) * _facet_row_h

    card = _make_card(card_x, card_y, card_w, card_h)
    view.addSubview_(card)
    content = card.contentView()

    # Toggle row — name + detail + switch
    row_y = card_h - _toggle_row_h
    name_y = row_y + (_toggle_row_h - 18) // 2 + (6 if detail else 0)
    name_label = _make_label(feature.description, _CARD_PAD, name_y, card_w - _CARD_PAD * 2 - 60, 13.0)
    content.addSubview_(name_label)

    if detail:
        detail_label = _make_secondary_label(detail, _CARD_PAD, name_y - 16, card_w - _CARD_PAD * 2 - 60, 10.0)
        detail_label.setTextColor_(NSColor.tertiaryLabelColor())
        content.addSubview_(detail_label)

    toggle = NSSwitch.alloc().initWithFrame_(
        NSMakeRect(card_w - _CARD_PAD - 46, row_y + (_toggle_row_h - 22) // 2, 46, 22)
    )
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

        if facet.type == FacetType.CHOICE:
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
        elif facet.type == FacetType.BOOL:
            val = features.get_facet(feature_key, facet.name)
            toggle = NSSwitch.alloc().initWithFrame_(NSMakeRect(card_w - _CARD_PAD - 46, fy + 9, 46, 22))
            toggle.setState_(NSControlStateValueOn if val else NSControlStateValueOff)
            toggle.setRepresentedObject_(f"{feature_key}|{facet.name}")
            toggle.setTarget_(delegate)
            toggle.setAction_(objc.selector(delegate.facetBoolChanged_, signature=b"v@:@"))
            toggle.setEnabled_(enabled)
            content.addSubview_(toggle)
            facet_controls.append(toggle)

    delegate._feature_controls[feature_key] = facet_controls


def _build_general_pane(delegate: _PrefsDelegate, w: int, h: int) -> NSView:  # noqa: PLR0915
    """Build the General pane — all features as stacked cards."""
    delegate._feature_controls = {}
    all_features = features.get_all()

    _toggle_row_h = 56  # taller for sub-description
    _facet_row_h = 40
    _card_gap = 8

    _danger_row_h = 38
    _danger_header_h = 34
    _danger_rows = 2
    _danger_h = _danger_header_h + _danger_row_h * _danger_rows
    _danger_gap = 16

    # Calculate total height needed
    # Header: 12px inset + 24px label + 8px gap = 44px
    _header_band = 44
    total_h = _header_band
    for f in all_features:
        feat_toggle_h = 56 if _FEATURE_DETAILS.get(f.key) else 44
        total_h += feat_toggle_h + len(f.facets) * _facet_row_h + _card_gap
    total_h += _danger_gap + _danger_h + _PAD
    inner_h = max(h, total_h)

    inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, inner_h))
    card_w = w - _PAD * 2

    y = _add_pane_header(inner, "General", w, inner_h)
    for feature in all_features:
        feat_toggle_h = 56 if _FEATURE_DETAILS.get(feature.key) else 44
        card_h = feat_toggle_h + len(feature.facets) * _facet_row_h
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
    """Build the history pane with search, sort, filter chips, and scrollable rows."""
    _reload_history_data()
    # Preserve sort state across pane switches — only init if not set
    if not hasattr(delegate, "_history_sort") or delegate._history_sort is None:
        delegate._history_search = ""
        delegate._history_sort = "date"
        delegate._history_sort_asc = False
        delegate._history_bookmarked_only = False

    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))

    below_header = _add_pane_header(view, "History", w, h)
    _toolbar_ctrl_h = 22
    toolbar_y = below_header - _toolbar_ctrl_h
    search = NSSearchField.alloc().initWithFrame_(NSMakeRect(_PAD, toolbar_y, 180, 22))
    search.setPlaceholderString_("Search...")
    search.setFont_(NSFont.systemFontOfSize_(12.0))
    search.setTarget_(delegate)
    search.setAction_(objc.selector(delegate.historySearchChanged_, signature=b"v@:@"))
    view.addSubview_(search)

    sort_seg = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(_PAD + 190, toolbar_y, 110, 22))
    sort_seg.setSegmentCount_(2)
    sort_seg.setLabel_forSegment_("Date \u2193", 0)  # default arrow
    sort_seg.setLabel_forSegment_("Name", 1)
    sort_seg.setWidth_forSegment_(52, 0)
    sort_seg.setWidth_forSegment_(50, 1)
    sort_seg.setSegmentStyle_(NSSegmentStyleTexturedRounded)
    sort_seg.setSelectedSegment_(0)
    sort_seg.setFont_(NSFont.systemFontOfSize_(11.0))
    sort_seg.setTarget_(delegate)
    sort_seg.setAction_(objc.selector(delegate.historySortChanged_, signature=b"v@:@"))
    view.addSubview_(sort_seg)

    bm_chip = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD + 310, toolbar_y - 1, 28, 24))
    bm_chip.setTitle_("")
    bm_chip.setImage_(sf_icon("bookmark.fill", size=12.0))
    bm_chip.setButtonType_(1)  # NSButtonTypeToggle
    bm_chip.setBezelStyle_(1)
    bm_chip.setState_(NSControlStateValueOff)
    bm_chip.setTarget_(delegate)
    bm_chip.setAction_(objc.selector(delegate.historyBookmarkFilter_, signature=b"v@:@"))
    bm_chip.setToolTip_("Show bookmarked only")
    bm_chip.setState_(NSControlStateValueOn if delegate._history_bookmarked_only else NSControlStateValueOff)
    view.addSubview_(bm_chip)

    # Restore sort state into controls
    sel_idx = 1 if delegate._history_sort == "name" else 0
    sort_seg.setSelectedSegment_(sel_idx)
    arrow = " \u2191" if delegate._history_sort_asc else " \u2193"
    for i, base in enumerate(("Date", "Name")):
        sort_seg.setLabel_forSegment_(base + arrow if i == sel_idx else base, i)

    content_top = toolbar_y - 10
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(0, content_top, w, 1))
    sep.setBoxType_(2)
    view.addSubview_(sep)

    scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, w, content_top))
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)
    view.addSubview_(scroll)

    delegate._history_scroll = scroll
    delegate._history_inner = None

    _rebuild_history_rows(delegate)
    return view


def _rebuild_history_rows(delegate: _PrefsDelegate) -> None:  # noqa: PLR0912, PLR0915
    """Rebuild the history row list based on current filter state."""
    scroll = delegate._history_scroll
    if scroll is None:
        return

    _reload_history_data()
    w = int(scroll.frame().size.width)
    h = int(scroll.frame().size.height)

    # Filter
    entries = list(_history_data)
    pinned_cwds = get_bookmark_service().get_bookmarked_cwds()

    if delegate._history_bookmarked_only:
        entries = [e for e in entries if e.get("cwd", "") in pinned_cwds]

    if delegate._history_search:
        q = delegate._history_search
        summary_svc = get_summary_service()
        filtered = []
        for e in entries:
            if q in e.get("project", "").lower():
                filtered.append(e)
            else:
                s = summary_svc.get_cached(e.get("cwd", ""))
                if s and q in s.lower():
                    filtered.append(e)
        entries = filtered

    # Sort
    asc = delegate._history_sort_asc
    if delegate._history_sort == "name":
        entries.sort(key=lambda e: e.get("project", "").lower(), reverse=not asc)
    elif asc:
        # Date — _reload_history_data returns newest first, so reverse for asc
        entries.reverse()

    # Build rows
    _row_h = 54
    _sep_h = 1

    if not entries:
        inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        empty = _make_secondary_label("No matching sessions.", _PAD, h // 2, w - _PAD * 2, 13.0)
        empty.setAlignment_(1)
        inner.addSubview_(empty)
        scroll.setDocumentView_(inner)
        return

    _list_pad = 8  # tight padding above first row and below last
    total_h = _list_pad + len(entries) * (_row_h + _sep_h) + _list_pad
    inner_h = max(h, total_h)
    inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, inner_h))

    pinned_cwds = get_bookmark_service().get_bookmarked_cwds()
    usage_svc = get_usage_service()
    summary_svc = get_summary_service()

    y = inner_h - _list_pad
    for i, entry in enumerate(entries):
        y -= _row_h
        _add_history_row(inner, delegate, entry, 0, y, w, _row_h, pinned_cwds, usage_svc, summary_svc)
        if i < len(entries) - 1:
            sep = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y - 1, w - _PAD * 2, _sep_h))
            sep.setBoxType_(2)
            inner.addSubview_(sep)
            y -= _sep_h

    scroll.setDocumentView_(inner)
    inner.scrollPoint_((0, inner_h))

    # Queue background generation for sessions missing summaries
    for entry in entries:
        cwd = entry.get("cwd", "")
        if cwd and summary_svc.get_cached(cwd) is None:
            summary_svc.track_session(cwd)


def _add_history_row(  # noqa: PLR0912, PLR0913, PLR0915
    view: NSView,
    delegate: _PrefsDelegate,
    entry: dict,
    _x: float,  # noqa: ARG001
    y: float,
    w: float,
    h: float,
    pinned_cwds: set[str],
    usage_svc: object,
    summary_svc: object,
) -> None:
    """Add a borderless history row — Finder list style."""
    project = entry.get("project", "unknown")
    cwd = entry.get("cwd", "")
    session_id = entry.get("session_id", "")
    model_raw = entry.get("model", "")
    model = MODEL_DISPLAY_NAMES.get(model_raw, model_raw)
    ended_at = entry.get("ended_at", "")
    is_pinned = cwd in pinned_cwds
    _p = _PAD

    # ── Line 1: [bookmark icon]  project name       ···
    _bm_col = _p  # bookmark icon column (fixed width)
    _name_col = _p + 18  # content starts after bookmark column
    ly1 = y + h - 20

    if is_pinned:
        mark = _make_label("▸", _bm_col, ly1, 14, 12.0)
        mark.setTextColor_(NSColor.secondaryLabelColor())
        view.addSubview_(mark)

    name_label = _make_label(project, _name_col, ly1, w - _name_col - 30, 13.0, bold=True)
    view.addSubview_(name_label)

    # ··· menu
    cached_title = summary_svc.get_cached_title(cwd) if cwd else None
    bullets = summary_svc.get_cached_summary(cwd) if cwd else None
    menu = NSMenu.alloc().init()

    # Bulleted summary at the top (if available)
    if bullets:
        _wrap = 55
        for line in bullets.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Word-wrap long lines (old-format summaries)
            if len(stripped) <= _wrap:
                si = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(stripped, None, "")
                si.setEnabled_(False)
                menu.addItem_(si)
            else:
                words = stripped.split()
                cur = ""
                for word in words:
                    test = f"{cur} {word}".strip()
                    if len(test) > _wrap and cur:
                        si = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(cur, None, "")
                        si.setEnabled_(False)
                        menu.addItem_(si)
                        cur = word
                    else:
                        cur = test
                if cur:
                    si = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(cur, None, "")
                    si.setEnabled_(False)
                    menu.addItem_(si)
        menu.addItem_(NSMenuItem.separatorItem())

    for mi_title, action, obj in [
        ("Resume", delegate.resumeSession_, f"{session_id}|{cwd}"),
        ("Activity", delegate.viewActivity_, f"{project}|{cwd}"),
    ]:
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(mi_title, None, "")
        mi.setRepresentedObject_(obj)
        mi.setTarget_(delegate)
        mi.setAction_(objc.selector(action, signature=b"v@:@"))
        menu.addItem_(mi)

    menu.addItem_(NSMenuItem.separatorItem())

    # Bookmark / Unbookmark
    if is_pinned:
        bm_mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Remove Bookmark", None, "")
        bm_mi.setRepresentedObject_(cwd)
        bm_mi.setTarget_(delegate)
        bm_mi.setAction_(objc.selector(delegate.unbookmarkSession_, signature=b"v@:@"))
    else:
        bm_mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Bookmark", None, "")
        bm_mi.setRepresentedObject_(f"{session_id}|{project}|{cwd}")
        bm_mi.setTarget_(delegate)
        bm_mi.setAction_(objc.selector(delegate.bookmarkSession_, signature=b"v@:@"))
    menu.addItem_(bm_mi)

    for mi_title, action, obj in [
        ("Copy Path", delegate.copyCwd_, cwd),
        ("Open in Finder", delegate.revealInFinder_, cwd),
    ]:
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(mi_title, None, "")
        mi.setRepresentedObject_(obj)
        mi.setTarget_(delegate)
        mi.setAction_(objc.selector(action, signature=b"v@:@"))
        menu.addItem_(mi)

    menu.addItem_(NSMenuItem.separatorItem())
    del_mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Delete", None, "")
    del_mi.setRepresentedObject_(cwd)
    del_mi.setTarget_(delegate)
    del_mi.setAction_(objc.selector(delegate.deleteHistoryEntry_, signature=b"v@:@"))
    d_attr = NSMutableAttributedString.alloc().initWithString_("Delete")
    d_attr.addAttribute_value_range_("NSColor", NSColor.systemRedColor(), NSRange(0, 6))
    del_mi.setAttributedTitle_(d_attr)
    menu.addItem_(del_mi)

    dots_btn = NSButton.alloc().initWithFrame_(NSMakeRect(w - _p - 22, ly1 - 1, 22, 18))
    dots_btn.setTitle_("···")
    dots_btn.setBordered_(False)
    dots_btn.setFont_(NSFont.systemFontOfSize_(12.0))
    dots_btn.setMenu_(menu)
    dots_btn.setAction_(objc.selector(delegate.showRowMenu_, signature=b"v@:@"))
    dots_btn.setTarget_(delegate)
    view.addSubview_(dots_btn)

    # ── Line 2: time · model · tokens (total)
    ly2 = ly1 - 17
    time_str = _relative_time(ended_at)
    tokens = usage_svc.get_tokens(cwd) if cwd else {}
    token_str = format_tokens_compact(tokens) if tokens else ""
    parts = [time_str]
    if model:
        parts.append(model)
    if token_str:
        parts.append(token_str)
    meta = "  ·  ".join(parts)
    meta_label = _make_secondary_label(meta, _name_col, ly2, w - _name_col - _p, 11.0)
    view.addSubview_(meta_label)

    # ── Line 3: title one-liner (full bullets in ··· menu)
    ly3 = ly2 - 16
    _max_title = 50
    if cached_title:
        s_text = cached_title[:_max_title] + "…" if len(cached_title) > _max_title else cached_title
        s_label = _make_secondary_label(s_text, _name_col, ly3, w - _name_col - _p, 11.0)
        s_label.setTextColor_(NSColor.tertiaryLabelColor())
        view.addSubview_(s_label)


_CHANGELOG = [
    (
        "v0.7.0",
        [
            "Sidebar preferences with feature toggles",
            "Session history with search, sort, and bookmark filter",
            "Smarter summaries: title + bulleted action list",
            "Background summary refresh (toggleable)",
            "Bookmarks submenu in menu bar",
            "Danger zone: clear bookmarks or summaries",
            "Settings stored in macOS preferences",
        ],
    ),
    (
        "v0.6.1",
        [
            "Native macOS notifications (no more terminal-notifier)",
            "Compact model names in menu bar",
        ],
    ),
    (
        "v0.6.0",
        [
            "One-click self-update from GitHub Releases",
            "Onboarding tips for new users",
            "Per-session token usage breakdown",
        ],
    ),
    (
        "v0.5.0",
        [
            "Onboarding tips and audit logging",
            "Session history recording",
            "Activity feed with timeline view",
        ],
    ),
    (
        "v0.4.0",
        [
            "Token usage tracking per session",
            "Auto-generated session summaries",
            "Pinned sessions with resume",
        ],
    ),
    (
        "v0.3.0",
        [
            "Preferences window with notification sounds",
            "Session history tab",
            "IDE detection (VS Code, PyCharm)",
        ],
    ),
]


def _build_usage_pane(delegate: _PrefsDelegate, w: int, h: int) -> NSView:  # noqa: PLR0915
    """Build the Usage pane — total accumulated stats + top sessions."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    y = _add_pane_header(view, "Usage", w, h)

    history = get_history_service().get_all()
    usage_svc = get_usage_service()

    # Gather per-session stats: (project, tokens, ended_at)
    session_stats: list[tuple[str, dict[str, int], str]] = []
    total: dict[str, int] = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
    _month_seconds = 30 * 86400
    now_ts = time.time()

    for entry in history:
        tokens = usage_svc.get_tokens(entry.cwd)
        session_total = sum(tokens.values())
        if session_total > 0:
            session_stats.append((entry.project, tokens, entry.ended_at))
            # Only count toward total if within past month
            try:
                ended = datetime.fromisoformat(entry.ended_at).timestamp()
                if now_ts - ended < _month_seconds:
                    for k in total:
                        total[k] += tokens[k]
            except (ValueError, TypeError, AttributeError):
                for k in total:
                    total[k] += tokens[k]

    total_sum = sum(total.values())
    card_w = w - _PAD * 2

    if total_sum == 0:
        no_data = _make_secondary_label("No usage data yet.", _PAD, y - 20, card_w, 13.0)
        view.addSubview_(no_data)
        return view

    # ── Section: Total usage ──
    y -= 14  # space below pane header
    total_header = _make_secondary_label("LAST 30 DAYS", _PAD, y, 200, 10.0)
    total_header.setTextColor_(NSColor.tertiaryLabelColor())
    view.addSubview_(total_header)
    y -= 6
    _row_h = 22
    total_lines = [
        ("Input", total["input"]),
        ("Output", total["output"]),
        ("Cache", total["cache_create"] + total["cache_read"]),
        ("Total", sum(total.values())),
    ]
    total_card_h = _CARD_PAD + len(total_lines) * _row_h + _CARD_PAD
    total_card = _make_card(_PAD, y - total_card_h, card_w, total_card_h)
    view.addSubview_(total_card)
    tc = total_card.contentView()

    ty = total_card_h - _CARD_PAD
    for label_text, count in total_lines:
        ty -= _row_h
        lbl = _make_label(label_text, _CARD_PAD, ty, 80, 12.0)
        lbl.setTextColor_(NSColor.secondaryLabelColor())
        tc.addSubview_(lbl)
        val = _make_label(_fmt_token_count(count), _CARD_PAD + 80, ty, card_w - _CARD_PAD * 2 - 80, 12.0, bold=True)
        val.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(12.0, 0.0))
        tc.addSubview_(val)

    y -= total_card_h + 16

    # ── Section: Top sessions by usage ──
    y -= 12
    top_header = _make_secondary_label("TOP SESSIONS BY USAGE", _PAD, y, 250, 10.0)
    top_header.setTextColor_(NSColor.tertiaryLabelColor())
    view.addSubview_(top_header)
    y -= 6

    session_stats.sort(key=lambda s: sum(s[1].values()), reverse=True)
    _top_n = 10
    top_entries = session_stats[:_top_n]
    _top_row_h = 22
    top_card_h = _CARD_PAD + len(top_entries) * _top_row_h + _CARD_PAD + 4
    top_card = _make_card(_PAD, y - top_card_h, card_w, top_card_h)
    view.addSubview_(top_card)
    tpc = top_card.contentView()

    # Column positions (all labels, no buttons — consistent baseline)
    _col_name = _CARD_PAD
    _col_date = _CARD_PAD + 170
    _col_tokens = _CARD_PAD + 250

    tpy = top_card_h - _CARD_PAD
    for project, tokens, ended_at in top_entries:
        tpy -= _top_row_h
        # Clickable name — use label-styled button at same y as labels
        name_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_col_name, tpy, 164, 18))
        name_btn.setTitle_(project)
        name_btn.setBordered_(False)
        name_btn.setFont_(NSFont.systemFontOfSize_(12.0))
        name_btn.setAlignment_(0)
        name_btn.setContentHuggingPriority_forOrientation_(750, 0)
        name_btn.setRepresentedObject_(project)
        name_btn.setTarget_(delegate)
        name_btn.setAction_(objc.selector(delegate.jumpToSession_, signature=b"v@:@"))
        tpc.addSubview_(name_btn)
        date_str = _relative_time(ended_at)
        date_label = _make_secondary_label(date_str, _col_date, tpy, 75, 11.0)
        tpc.addSubview_(date_label)
        total_tok = sum(tokens.values())
        val = _make_secondary_label(
            _fmt_token_count(total_tok), _col_tokens, tpy, card_w - _CARD_PAD - _col_tokens, 11.0
        )
        val.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(11.0, 0.0))
        tpc.addSubview_(val)

    # Action buttons
    y -= top_card_h + 20
    btn_y = y
    _btn_h = 24
    _btn_font = NSFont.systemFontOfSize_(11.0)

    claude_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD, btn_y, 140, _btn_h))
    claude_btn.setTitle_("Open in Claude")
    claude_btn.setBezelStyle_(1)
    claude_btn.setFont_(_btn_font)
    claude_btn.setTarget_(delegate)
    claude_btn.setAction_(objc.selector(delegate.openClaudeUsage_, signature=b"v@:@"))
    view.addSubview_(claude_btn)

    return view


def _fmt_token_count(n: int) -> str:
    """Format token count with suffix: 1.2M, 45K, 123."""
    _m = 1_000_000
    _k = 1000
    if n >= _m:
        return f"{n / _m:.1f}M tokens"
    if n >= _k:
        return f"{n / _k:.0f}K tokens"
    return f"{n} tokens"


def _build_about_pane(delegate: _PrefsDelegate, w: int, h: int) -> NSView:  # noqa: PLR0915
    """Build the about pane with version, links, and changelog."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))

    y = _add_pane_header(view, "About", w, h)

    # Version + buttons card
    card_h = 80
    card_w = w - _PAD * 2
    card = _make_card(_PAD, y - card_h, card_w, card_h)
    view.addSubview_(card)
    content = card.contentView()

    ver_label = _make_label(f"ClaudeWatch v{__version__}", _CARD_PAD, card_h - _CARD_PAD - 18, 300, 14.0, bold=True)
    content.addSubview_(ver_label)

    btn_y = _CARD_PAD
    log_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, btn_y, 100, 24))
    log_btn.setTitle_("Audit Log")
    log_btn.setBezelStyle_(1)
    log_btn.setFont_(NSFont.systemFontOfSize_(11.0))
    log_btn.setTarget_(delegate)
    log_btn.setAction_(objc.selector(delegate.viewAuditLog_, signature=b"v@:@"))
    content.addSubview_(log_btn)

    repo_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_CARD_PAD + 108, btn_y, 80, 24))
    repo_btn.setTitle_("GitHub")
    repo_btn.setBezelStyle_(1)
    repo_btn.setFont_(NSFont.systemFontOfSize_(11.0))
    repo_btn.setTarget_(delegate)
    repo_btn.setAction_(objc.selector(delegate.openRepo_, signature=b"v@:@"))
    content.addSubview_(repo_btn)

    y -= card_h + 24

    # Changelog in a scrollable card
    y -= 12
    changelog_label = _make_secondary_label("WHAT'S NEW", _PAD, y, 200, 10.0)
    changelog_label.setTextColor_(NSColor.tertiaryLabelColor())
    view.addSubview_(changelog_label)
    y -= 6

    _ver_h = 18
    _bullet_h = 14
    _ver_gap = 8
    _cl_pad = 10  # inner padding for changelog
    inner_content_h = _cl_pad
    for _ver, items in _CHANGELOG:
        inner_content_h += _ver_h + len(items) * _bullet_h + _ver_gap
    inner_content_h += _cl_pad

    changelog_card_h = min(y - 8, inner_content_h)  # 8px bottom margin
    changelog_card = _make_card(_PAD, y - changelog_card_h, card_w, changelog_card_h)
    view.addSubview_(changelog_card)

    scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, card_w, changelog_card_h))
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)

    inner_h = max(changelog_card_h, inner_content_h)
    inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, card_w, inner_h))
    cy = inner_h - _cl_pad

    for version, items in _CHANGELOG:
        cy -= _ver_h
        ver = _make_label(version, _cl_pad, cy, 200, 11.0, bold=True)
        inner.addSubview_(ver)
        for item in items:
            cy -= _bullet_h
            bullet = _make_secondary_label(f"• {item}", _cl_pad + 8, cy, card_w - _cl_pad * 2 - 20, 10.0)
            inner.addSubview_(bullet)
        cy -= _ver_gap

    scroll.setDocumentView_(inner)
    inner.scrollPoint_((0, inner_h))
    changelog_card.contentView().addSubview_(scroll)

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
