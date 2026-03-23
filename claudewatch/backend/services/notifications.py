"""macOS notifications via terminal-notifier.

Uses the terminal-notifier binary for reliable notification delivery on
macOS 13+. NSUserNotificationCenter is deprecated and silently drops
notifications on modern macOS.

Requires: brew install terminal-notifier
"""

import logging
import os
import shutil
import subprocess
import time

from claudewatch.backend.helpers import run_applescript
from claudewatch.backend.models import ClaudeSession, HostApp
from claudewatch.backend.repositories.config import get_setting

_BUNDLE_IDS: dict[HostApp, str] = {
    HostApp.TERMINAL: "com.apple.Terminal",
    HostApp.VSCODE: "com.microsoft.VSCode",
    HostApp.PYCHARM: "com.jetbrains.pycharm",
}

log = logging.getLogger("claudewatch")

# Resolve terminal-notifier, preferring trusted Homebrew paths
_TRUSTED_PATHS = ("/opt/homebrew/bin/terminal-notifier", "/usr/local/bin/terminal-notifier")
TERMINAL_NOTIFIER: str | None = None
for _p in _TRUSTED_PATHS:
    if os.path.isfile(_p) and os.access(_p, os.X_OK):
        TERMINAL_NOTIFIER = _p
        break
if TERMINAL_NOTIFIER is None:
    TERMINAL_NOTIFIER = shutil.which("terminal-notifier")


def _get_frontmost_window() -> tuple[str, str]:
    """Return (app_name, window_title) of the frontmost window."""
    result = run_applescript("""
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set frontName to name of frontApp
        set winTitle to ""
        try
            set winTitle to name of front window of frontApp
        end try
    end tell
    return frontName & "|" & winTitle
    """)
    if "|" in result:
        app, title = result.split("|", 1)
        return app, title
    return "", ""


class NotificationManager:
    def __init__(self) -> None:
        self._notified_pids: set[int] = set()
        self.cooldown = 30.0
        self.last_notification_time = 0.0

    def notify_if_needed(self, sessions: list[ClaudeSession]) -> None:
        if not TERMINAL_NOTIFIER or not get_setting("notifications_enabled"):
            return

        attention = [s for s in sessions if s.needs_attention]
        if not attention:
            live_pids = {s.pid for s in sessions}
            self._notified_pids = {p for p in self._notified_pids if p in live_pids}
            return

        new_attention = [s for s in attention if s.pid not in self._notified_pids]
        if not new_attention:
            return

        now = time.time()
        if now - self.last_notification_time < self.cooldown:
            return

        front_app, front_title = _get_frontmost_window()
        new_attention = [s for s in new_attention if f" {s.project} " not in f" {front_title} "]
        if not new_attention:
            return

        self.last_notification_time = now

        for s in new_attention:
            title = "Claude needs approval"
            subtitle = s.project
            message = s.prompt_text if s.prompt_text else "Waiting for permission"

            log.info(
                "notification.sent project=%s action=%s host=%s pid=%d",
                s.project,
                s.prompt_text or "permission",
                s.host_app.value,
                s.pid,
            )

            cmd = [
                TERMINAL_NOTIFIER,
                "-title",
                title,
                "-message",
                message[:200],
                "-subtitle",
                subtitle,
                "-sound",
                str(get_setting("notification_sound")),
                "-group",
                f"claudewatch-{s.pid}",
                "-sender",
                _BUNDLE_IDS.get(s.host_app, "com.apple.Terminal"),
            ]

            if s.host_app == HostApp.TERMINAL and s.window_id is not None:
                # Raise only the specific window, not all Terminal windows.
                # window_id is always int — validated via isdigit() in detection.py
                wid = s.window_id
                cmd.extend(
                    [
                        "-execute",
                        (
                            f"osascript"
                            f" -e 'tell application \"Terminal\" to set miniaturized of window id {wid} to false'"
                            f" -e 'tell application \"Terminal\" to set index of window id {wid} to 1'"
                            f' -e \'tell application "System Events" to set frontmost of process "Terminal" to true\''
                        ),
                    ]
                )
            elif s.host_app in _BUNDLE_IDS:
                cmd.extend(["-activate", _BUNDLE_IDS[s.host_app]])

            try:
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
                self._notified_pids.add(s.pid)
            except (OSError, subprocess.TimeoutExpired):
                pass

        live_attention_pids = {s.pid for s in attention}
        self._notified_pids &= live_attention_pids
