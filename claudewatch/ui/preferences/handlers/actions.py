"""General action handlers — resume, activity, clear, open."""

from __future__ import annotations

import os
import re
import subprocess

from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSPasteboard,
    NSPasteboardTypeString,
)

from claudewatch.backend.bookmark.dependencies import get_bookmark_service
from claudewatch.backend.core.helpers import escape_applescript, run_applescript
from claudewatch.backend.core.paths import LOG_PATH
from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.summary.dependencies import get_summary_service
from claudewatch.ui.activity import show_activity
from claudewatch.ui.safety import get_represented_object


def handle_resume(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Resume a session in Terminal."""
    data = get_represented_object(sender)
    if "|" not in data:
        return
    sid, cwd = data.split("|", 1)
    if not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", sid):
        return
    safe_cwd = escape_applescript(cwd)
    run_applescript(f'''
        tell application "Terminal"
            activate
            do script "cd \\"{safe_cwd}\\" && claude -r {sid}"
        end tell
    ''')


def handle_view_activity(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Open the activity window for a session."""
    data = get_represented_object(sender)
    if "|" not in data:
        return
    project, cwd = data.split("|", 1)
    show_activity(project, cwd)


def handle_copy_cwd(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Copy project path to clipboard."""
    cwd = get_represented_object(sender)
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(cwd, NSPasteboardTypeString)


def handle_reveal_in_finder(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Open project directory in Finder."""
    cwd = get_represented_object(sender)
    if os.path.isdir(cwd):
        subprocess.run(["open", cwd], check=False)  # noqa: S603, S607


def handle_clear_bookmarks(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Clear all bookmarks with confirmation dialog."""
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Delete all bookmarks?")
    alert.setInformativeText_("This will remove all pinned sessions. This cannot be undone.")
    alert.addButtonWithTitle_("Delete All")
    alert.addButtonWithTitle_("Cancel")
    if alert.runModal() == NSAlertFirstButtonReturn:
        get_bookmark_service().clear_all()


def handle_clear_summaries(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Clear all cached summaries with confirmation dialog."""
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Delete all summaries?")
    alert.setInformativeText_("Cached summaries will be regenerated as needed. This cannot be undone.")
    alert.addButtonWithTitle_("Delete All")
    alert.addButtonWithTitle_("Cancel")
    if alert.runModal() == NSAlertFirstButtonReturn:
        get_summary_service().clear_all()


def handle_open_claude_usage(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Open claude /usage in Terminal using a trusted project directory."""
    history = get_history_service().get_all()
    cwd = ""
    # Prefer real project dirs over worktrees/temp dirs
    skip_patterns = (".claude/worktrees", "/tmp/", "/var/folders/")  # noqa: S108
    for entry in history:
        if not entry.cwd or not os.path.isdir(entry.cwd):
            continue
        if any(p in entry.cwd for p in skip_patterns):
            continue
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


def handle_view_audit_log(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Open the audit log in Console.app."""
    if os.path.exists(LOG_PATH):
        subprocess.run(["open", "-a", "Console", LOG_PATH], check=False)  # noqa: S603, S607
