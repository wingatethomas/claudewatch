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
    """Remove a session from bookmarks."""
    cwd = get_represented_object(sender)
    get_bookmark_service().remove(cwd)
    from claudewatch.ui.preferences.panes.sessions import rebuild_rows

    rebuild_rows(delegate)


def handle_delete(delegate: object, sender: object) -> None:
    """Delete a history entry with confirmation."""
    cwd = get_represented_object(sender)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Delete this session from history?")
    alert.setInformativeText_("This cannot be undone.")
    alert.addButtonWithTitle_("Delete")
    alert.addButtonWithTitle_("Cancel")
    if alert.runModal() == NSAlertFirstButtonReturn:
        get_history_service().remove(cwd)
        from claudewatch.ui.preferences.panes.sessions import rebuild_rows

        rebuild_rows(delegate)
