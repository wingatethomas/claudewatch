"""Preferences delegate — thin dispatch to handler modules."""

from __future__ import annotations

import objc
from AppKit import NSColor, NSView
from Foundation import NSMakeRect, NSObject

from claudewatch.ui.safety import get_represented_object, objc_callback


class PrefsDelegate(NSObject):
    """Single NSObject delegate — routes events to handler modules."""

    # Instance vars (set by window.py)
    _sidebar_items: list[dict]
    _sidebar_btns: list
    _pane_classes: dict
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

        pane_class = self._pane_classes.get(item["key"])
        if not pane_class:
            return

        pane = pane_class(self, self._content_w, self._content_h)
        view = pane.build()
        view.setFrame_(NSMakeRect(0, 0, self._content_w, self._content_h))
        self._content_area.addSubview_(view)
        self._current_pane = view

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
    def graphTabChanged_(self, sender: objc.objc_object) -> None:  # noqa: N802
        self._graph_tab = sender.selectedSegment()
        self.show_pane({"key": "graph"})

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
    def openClaudeAiUsage_(self, sender: objc.objc_object) -> None:  # noqa: N802
        import webbrowser

        webbrowser.open("https://claude.ai/settings/usage")

    @objc_callback
    def viewAuditLog_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.preferences.handlers.actions import handle_view_audit_log

        handle_view_audit_log(self, sender)

    @objc_callback
    def openRepo_(self, sender: objc.objc_object) -> None:  # noqa: N802
        import webbrowser

        webbrowser.open("https://github.com/wingatethomas/claudewatch")

    @objc_callback
    def testNotification_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.backend.notifications.dependencies import get_notification_service

        get_notification_service().send("Test notification", "ClaudeWatch", "Notifications are working!")

    @objc_callback
    def testSound_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from AppKit import NSSound

        from claudewatch.backend.core import features

        sound_name = features.get_facet("notifications", "sound") or "Glass"
        sound = NSSound.soundNamed_(sound_name)
        if sound:
            sound.play()

    @objc_callback
    def showWelcome_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.welcome import show_welcome

        show_welcome()

    # -- Security --

    @objc_callback
    def removePermission_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.safety import get_represented_object

        info = get_represented_object(sender)
        if "|" not in info:
            return
        settings_path, rule = info.split("|", 1)

        from claudewatch.backend.security.dependencies import get_security_service

        repo = get_security_service().repository
        # Show what's being removed in the confirmation
        from claudewatch.ui.preferences.panes.security import SecurityPane

        display = SecurityPane.format_permission_display(rule)
        if repo.remove_permission_rule(settings_path, rule):
            self._show_security_confirmation(f"Removed: {display}")

    @objc_callback
    def clearPermissions_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.safety import get_represented_object

        settings_path = get_represented_object(sender)
        if not settings_path:
            return

        from claudewatch.backend.security.dependencies import get_security_service

        repo = get_security_service().repository
        if repo.clear_permissions(settings_path):
            self._show_security_confirmation("All permissions cleared")

    @objc_callback
    def uninstallPlugin_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from AppKit import NSAlert, NSAlertFirstButtonReturn

        from claudewatch.ui.safety import get_represented_object

        plugin_name = get_represented_object(sender)
        if not plugin_name:
            return

        short_name = plugin_name.split("@")[0] if "@" in plugin_name else plugin_name

        # Confirm before uninstalling
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"Uninstall {short_name}?")
        alert.setInformativeText_("This removes the plugin from Claude Code. You can reinstall it later.")
        alert.addButtonWithTitle_("Uninstall")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() != NSAlertFirstButtonReturn:
            return

        from claudewatch.backend.security.dependencies import get_security_service

        repo = get_security_service().repository
        if repo.uninstall_plugin(plugin_name):
            self._show_security_confirmation(f"{short_name} uninstalled")

    @objc_callback
    def removeDangerousPermissions_(self, sender: objc.objc_object) -> None:  # noqa: N802
        from claudewatch.ui.safety import get_represented_object

        settings_path = get_represented_object(sender)
        if not settings_path:
            return

        from claudewatch.backend.security.dependencies import get_security_service

        repo = get_security_service().repository
        removed = repo.remove_dangerous_permissions(settings_path)
        if removed > 0:
            self._show_security_confirmation(f"{removed} dangerous permission(s) removed")

    @objc_callback
    def openBlocklistSource_(self, sender: objc.objc_object) -> None:  # noqa: N802, ARG002
        import webbrowser

        webbrowser.open("https://github.com/anthropics/claude-plugins-official")

    def _show_security_confirmation(self, message: str) -> None:
        """Show confirmation alert then refresh the Security pane preserving scroll."""
        from AppKit import NSAlert

        # Save scroll position before rebuild
        scroll_y = self._get_security_scroll_position()

        alert = NSAlert.alloc().init()
        alert.setMessageText_(message)
        alert.setInformativeText_("Claude will ask for permission again next time it needs access.")
        alert.addButtonWithTitle_("OK")
        alert.runModal()

        self.show_pane({"key": "security"})

        # Restore scroll position after rebuild
        self._restore_security_scroll_position(scroll_y)

    def _get_security_scroll_position(self) -> float:
        """Get current scroll Y offset from the Security pane's scroll view."""
        content_area = getattr(self, "_content_area", None)
        if not content_area:
            return 0
        for subview in content_area.subviews():
            for child in subview.subviews():
                if hasattr(child, "documentView") and child.documentView():
                    doc = child.documentView()
                    visible = child.documentVisibleRect()
                    return doc.frame().size.height - visible.origin.y
        return 0

    def _restore_security_scroll_position(self, saved_y: float) -> None:
        """Restore scroll position after pane rebuild."""
        if saved_y <= 0:
            return
        content_area = getattr(self, "_content_area", None)
        if not content_area:
            return
        for subview in content_area.subviews():
            for child in subview.subviews():
                if hasattr(child, "documentView") and child.documentView():
                    doc = child.documentView()
                    new_origin_y = doc.frame().size.height - saved_y
                    doc.scrollPoint_((0, max(0, new_origin_y)))
                    return

    # -- Window --

    @objc_callback
    def windowWillClose_(self, notification: objc.objc_object) -> None:  # noqa: N802, ARG002
        from claudewatch.ui.preferences import window

        window._window = None
