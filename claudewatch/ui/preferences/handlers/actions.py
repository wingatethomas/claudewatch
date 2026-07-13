"""General action handlers — resume, activity, clear, open."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys

from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSPasteboard,
    NSPasteboardTypeString,
)

from claudewatch import __version__
from claudewatch.backend.bookmark.dependencies import get_bookmark_service
from claudewatch.backend.core.helpers import escape_applescript, run_applescript
from claudewatch.backend.core.paths import LOG_PATH
from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.summary.dependencies import get_summary_service
from claudewatch.ui.activity import show_activity
from claudewatch.ui.safety import get_represented_object

_DIAGNOSTIC_TAIL_BYTES = 50_000


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
        do shell script "open -a Terminal \\"{safe_cwd}\\""
        delay 0.5
        tell application "Terminal"
            do script "claude -r {sid}" in front window
        end tell
    ''')


def handle_view_activity(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Open the activity window for a session.

    Payload is "project|cwd|session_id"; legacy 2-part payloads omit session_id.
    """
    data = get_represented_object(sender)
    if "|" not in data:
        return
    parts = data.split("|", 2)
    project, cwd = parts[0], parts[1]
    session_id = parts[2] if len(parts) > 2 else ""
    show_activity(project, cwd, session_id)


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
    home = os.path.expanduser("~")
    # Prefer real project dirs over worktrees/temp/home dirs
    skip_patterns = (".claude/worktrees", "/tmp/", "/var/folders/")  # noqa: S108  # nosec B108 - matching paths, not creating tempfiles
    for entry in history:
        if not entry.cwd or not os.path.isdir(entry.cwd):
            continue
        if entry.cwd == home:
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


def build_diagnostic_text(log_path: str = LOG_PATH, *, tail_bytes: int = _DIAGNOSTIC_TAIL_BYTES) -> str:
    """Build a diagnostic blob for paste-into-issue: version banner + log tail.

    The audit log already excludes session content, prompts, and assistant
    output (per privacy.md), so the tail is safe to share. The banner adds the
    minimum context a maintainer needs to triage: app version, macOS version,
    Python version, and log size.
    """
    banner_lines = [
        f"ClaudeWatch v{__version__}",
        f"macOS {platform.mac_ver()[0] or 'unknown'}",
        f"Python {sys.version.split()[0]}",
    ]
    log_tail = ""
    log_note = ""
    try:
        size = os.path.getsize(log_path)
        with open(log_path, "rb") as f:
            if size > tail_bytes:
                f.seek(size - tail_bytes)
            raw = f.read()
        if size > tail_bytes:
            # When the seek lands mid-line, drop everything up to the first newline.
            # Skip the discard if doing so would leave nothing — a single huge line
            # is better than no log at all.
            idx = raw.find(b"\n")
            if 0 <= idx < len(raw) - 1:
                raw = raw[idx + 1 :]
        log_tail = raw.decode("utf-8", errors="replace")
        log_note = f"--- claudewatch.log (last {len(log_tail)} bytes of {size}) ---"
    except OSError:
        log_note = f"--- claudewatch.log unreadable at {log_path} ---"
    return "\n".join([*banner_lines, "", log_note, log_tail])


def handle_copy_diagnostic(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Copy a paste-ready diagnostic blob to the clipboard for issue reports."""
    text = build_diagnostic_text()
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)
