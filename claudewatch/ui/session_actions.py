"""Session lifecycle actions — exit, pause, resume, accessibility check."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time

from claudewatch.backend.core.helpers import escape_applescript, is_accessibility_trusted, run_applescript
from claudewatch.backend.notifications.dependencies import get_notification_service

log = logging.getLogger("claudewatch")


def clean_exit_session(tty: str, pid: int, project: str, window_id: int | None = None) -> bool:
    """Send SIGINT to exit Claude Code, then close the Terminal tab.

    Claude Code handles SIGINT gracefully — saves session state,
    making it resumable with --resume.
    """
    try:
        os.kill(pid, signal.SIGINT)
        log.info("session.exit project=%s pid=%d tty=%s", project, pid, tty)
    except OSError:
        log.warning("session.exit failed project=%s pid=%d", project, pid)
        return False

    # Close the terminal tab after Claude actually exits
    if window_id is not None:
        # window_id is always int — validated via isdigit() in detection.py
        def _close_tab() -> None:
            # Poll until the process exits (max 10s, check every 0.5s)
            _max_wait = 20
            for _ in range(_max_wait):
                time.sleep(0.5)
                try:
                    os.kill(pid, 0)  # 0 signal = check if alive
                except OSError:
                    break  # process has exited
            run_applescript(f"""
                tell application "Terminal"
                    close window id {window_id} saving no
                end tell
            """)

        threading.Thread(target=_close_tab, daemon=True).start()
    return True


def notify_paused(project: str) -> None:
    """Send a 'session paused' notification."""
    get_notification_service().send("Session paused", project, "Resume from the Pinned section")


def open_terminal_and_run(command: str, cwd: str = "") -> None:
    """Run a shell command in a new Terminal window, cd'ing to cwd first if given.

    A bare ``do script`` opens a new window — no positional window references,
    which race the window opening. Callers build ``command`` from validated
    parts (e.g. UUID-checked session IDs); everything interpolated here is
    escaped via ``escape_applescript``.
    """
    safe_command = escape_applescript(command)
    if cwd:
        safe_cwd = escape_applescript(cwd)
        shell = f'"cd " & quoted form of "{safe_cwd}" & " && {safe_command}"'
    else:
        shell = f'"{safe_command}"'
    run_applescript(f"""
        tell application "Terminal"
            activate
            do script {shell}
        end tell
    """)


__all__ = ["clean_exit_session", "is_accessibility_trusted", "notify_paused", "open_terminal_and_run"]
