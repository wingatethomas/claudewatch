"""Preferences delegate — thin dispatch to handler modules."""

from __future__ import annotations

import objc
from AppKit import NSColor, NSView
from Foundation import NSObject

from claudewatch.ui.safety import get_represented_object, objc_callback


class PrefsDelegate(NSObject):
    """Single NSObject delegate — routes events to handler modules."""

    # Instance vars (set by window.py)
    _sidebar_items: list[dict]
    _sidebar_btns: list
    _pane_builders: dict
    _content_w: float
    _content_h: float
    _content_area: NSView | None
    _current_pane: NSView | None
    _feature_controls: dict
    _selected_idx: int
    # History state
    _history_search: str
    _history_sort: str
    _history_sort_asc: bool
    _history_bookmarked_only: bool
    _history_scroll: object | None
    _history_inner: object | None

    # -- Pane management --

    def show_pane(self, item: dict) -> None:
        """Remove current pane and show new one."""
        if self._current_pane is not None:
            self._current_pane.removeFromSuperview()
            self._current_pane = None

        builder = self._pane_builders.get(item["key"])
        if not builder:
            return

        from Foundation import NSMakeRect

        pane = builder(self, self._content_w, self._content_h)
        pane.setFrame_(NSMakeRect(0, 0, self._content_w, self._content_h))
        self._content_area.addSubview_(pane)
        self._current_pane = pane

    def select_sidebar(self, idx: int) -> None:
        """Update sidebar highlight and show corresponding pane."""
        # Unhighlight previous
        if hasattr(self, "_selected_idx") and 0 <= self._selected_idx < len(self._sidebar_btns):
            old_btn = self._sidebar_btns[self._selected_idx]
            if old_btn is not None:
                old_btn.wantsLayer()
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
                self.show_pane(item)

    # -- Sidebar --

    @objc_callback
    def sidebarClicked_(self, sender: objc.objc_object) -> None:  # noqa: N802
        tag = sender.tag()
        if 0 <= tag < len(self._sidebar_items):
            item = self._sidebar_items[tag]
            if item["type"] != "separator":
                self.select_sidebar(tag)

    # -- Features --

    @objc_callback
    def featureToggled_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.features import handle_toggle

        handle_toggle(self, sender)

    @objc_callback
    def facetChanged_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.features import handle_facet_change

        handle_facet_change(self, sender)

    @objc_callback
    def facetBoolChanged_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.features import handle_facet_bool_change

        handle_facet_bool_change(self, sender)

    # -- History --

    @objc_callback
    def historySearchChanged_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.history import handle_search_changed

        handle_search_changed(self, sender)

    @objc_callback
    def historySortChanged_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.history import handle_sort_changed

        handle_sort_changed(self, sender)

    @objc_callback
    def historyBookmarkFilter_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.history import handle_bookmark_filter

        handle_bookmark_filter(self, sender)

    @objc_callback
    def showRowMenu_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.history import handle_show_row_menu

        handle_show_row_menu(self, sender)

    @objc_callback
    def bookmarkSession_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.history import handle_bookmark

        handle_bookmark(self, sender)

    @objc_callback
    def unbookmarkSession_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.history import handle_unbookmark

        handle_unbookmark(self, sender)

    @objc_callback
    def deleteHistoryEntry_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.history import handle_delete

        handle_delete(self, sender)

    @objc_callback
    def resumeSession_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.actions import handle_resume

        handle_resume(self, sender)

    @objc_callback
    def viewActivity_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.actions import handle_view_activity

        handle_view_activity(self, sender)

    # -- Navigation --

    @objc_callback
    def jumpToSession_(self, sender: objc.objc_object) -> None:  # noqa: N802
        project = get_represented_object(sender)
        self._history_search = project.lower()
        self._history_sort = getattr(self, "_history_sort", "date")
        self._history_sort_asc = getattr(self, "_history_sort_asc", False)
        self._history_bookmarked_only = False
        for i, item in enumerate(self._sidebar_items):
            if item.get("key") == "history":
                self.select_sidebar(i)
                break

    # -- Static actions --

    @objc_callback
    def copyCwd_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.actions import handle_copy_cwd

        handle_copy_cwd(self, sender)

    @objc_callback
    def revealInFinder_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.actions import handle_reveal_in_finder

        handle_reveal_in_finder(self, sender)

    @objc_callback
    def clearBookmarks_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.actions import handle_clear_bookmarks

        handle_clear_bookmarks(self, sender)

    @objc_callback
    def clearSummaries_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.actions import handle_clear_summaries

        handle_clear_summaries(self, sender)

    @objc_callback
    def openClaudeUsage_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.actions import handle_open_claude_usage

        handle_open_claude_usage(self, sender)

    @objc_callback
    def openAnthropicConsole_(self, sender: objc.objc_object) -> None:  # noqa: N802
        import webbrowser

        webbrowser.open("https://console.anthropic.com/settings/usage")

    @objc_callback
    def viewAuditLog_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.actions import handle_view_audit_log

        handle_view_audit_log(self, sender)

    @objc_callback
    def openRepo_(self, sender: objc.objc_object) -> None:  # noqa: N802
        import webbrowser

        webbrowser.open("https://github.com/wingatethomas/claudewatch")

    # -- Window --

    @objc_callback
    def windowWillClose_(self, notification: objc.objc_object) -> None:  # noqa: N802, ARG002
        from claudewatch.ui.preferences import window as _win_mod

        _win_mod._window = None
