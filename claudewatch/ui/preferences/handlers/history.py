"""History pane handlers — search, sort, filter, bookmark, delete."""

from __future__ import annotations

from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSControlStateValueOn,
    NSMenu,
)

from claudewatch.backend.bookmark.dependencies import get_bookmark_service
from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.ui.safety import get_represented_object


def handle_search_changed(delegate: object, sender: object) -> None:
    """Update search query and rebuild rows."""
    delegate._history_search = str(sender.stringValue()).strip().lower()
    from claudewatch.ui.preferences.panes.sessions import rebuild_rows

    rebuild_rows(delegate)


def handle_sort_changed(delegate: object, sender: object) -> None:
    """Toggle sort direction or switch sort key, rebuild rows."""
    idx = sender.selectedSegment()
    new_sort = "name" if idx == 1 else "date"
    if new_sort == delegate._history_sort:
        delegate._history_sort_asc = not delegate._history_sort_asc
    else:
        delegate._history_sort = new_sort
        delegate._history_sort_asc = new_sort == "name"
    # Update segment labels
    arrow_up = " \u2191"
    arrow_down = " \u2193"
    for i, base in enumerate(("Date", "Name")):
        if i == idx:
            arrow = arrow_up if delegate._history_sort_asc else arrow_down
            sender.setLabel_forSegment_(base + arrow, i)
        else:
            sender.setLabel_forSegment_(base, i)
    from claudewatch.ui.preferences.panes.sessions import rebuild_rows

    rebuild_rows(delegate)


def handle_clear_stale(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Remove history entries whose session logs are gone, after confirmation."""
    history = get_history_service()
    stale_count = sum(1 for e in history.get_all() if not history.logs_exist(e.cwd, e.session_id))
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    if not stale_count:
        alert.setMessageText_("No stale entries")
        alert.setInformativeText_("Every recorded session still has its logs on disk.")
        alert.addButtonWithTitle_("OK")
        alert.runModal()
        return
    alert.setMessageText_(f"Clear {stale_count} stale {'entry' if stale_count == 1 else 'entries'}?")
    alert.setInformativeText_(
        "These sessions' logs are gone (deleted worktrees, moved projects). This cannot be undone."
    )
    alert.addButtonWithTitle_("Clear")
    alert.addButtonWithTitle_("Cancel")
    if alert.runModal() == NSAlertFirstButtonReturn:
        history.remove_stale()
        from claudewatch.ui.preferences.panes.sessions import rebuild_rows

        rebuild_rows(delegate)


def handle_bookmark_filter(delegate: object, sender: object) -> None:
    """Toggle bookmarked-only filter."""
    delegate._history_bookmarked_only = sender.state() == NSControlStateValueOn
    from claudewatch.ui.preferences.panes.sessions import rebuild_rows

    rebuild_rows(delegate)


def handle_show_row_menu(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Pop up context menu for a history row."""
    menu = sender.menu()
    if menu:
        NSMenu.popUpContextMenu_withEvent_forView_(menu, NSApplication.sharedApplication().currentEvent(), sender)


def handle_bookmark(delegate: object, sender: object) -> None:
    """Add a session to bookmarks."""
    data = get_represented_object(sender)
    if "|" not in data:
        return
    sid, rest = data.split("|", 1)
    project, cwd = rest.split("|", 1) if "|" in rest else ("", rest)
    get_bookmark_service().add(sid, project, cwd, "")
    from claudewatch.ui.preferences.panes.sessions import rebuild_rows

    rebuild_rows(delegate)


def handle_unbookmark(delegate: object, sender: object) -> None:
    """Remove a session from bookmarks. Payload is 'session_id|cwd' (or bare cwd)."""
    data = get_represented_object(sender)
    sid, cwd = data.split("|", 1) if "|" in data else ("", data)
    get_bookmark_service().remove(sid, cwd)
    from claudewatch.ui.preferences.panes.sessions import rebuild_rows

    rebuild_rows(delegate)


def handle_delete(delegate: object, sender: object) -> None:
    """Delete a history entry with confirmation. Payload is 'session_id|cwd' (or bare cwd)."""
    data = get_represented_object(sender)
    sid, cwd = data.split("|", 1) if "|" in data else ("", data)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Delete this session from history?")
    alert.setInformativeText_("This cannot be undone.")
    alert.addButtonWithTitle_("Delete")
    alert.addButtonWithTitle_("Cancel")
    if alert.runModal() == NSAlertFirstButtonReturn:
        get_history_service().remove(sid, cwd)
        from claudewatch.ui.preferences.panes.sessions import rebuild_rows

        rebuild_rows(delegate)
