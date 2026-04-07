"""macOS notifications via NSUserNotificationCenter.

Uses the native (deprecated but functional) NSUserNotification API.
Handles click actions to focus the session window.
"""

import logging
import time

from Foundation import NSObject, NSUserNotification, NSUserNotificationCenter

from claudewatch.backend.core import features
from claudewatch.backend.core.helpers import is_accessibility_trusted, run_applescript
from claudewatch.backend.core.models import ClaudeSession
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.notifications.models import FrontmostWindow

log = logging.getLogger("claudewatch")

# Focus callback — set by menubar.py at startup
_focus_callback = None


def set_focus_callback(callback: object) -> None:
    """Register a callback for notification click → focus session."""
    global _focus_callback  # noqa: PLW0603
    _focus_callback = callback


def _get_frontmost_window() -> FrontmostWindow:
    """Return the frontmost macOS window."""
    if not is_accessibility_trusted():
        log.warning("notifications: skipping System Events — Accessibility permission not granted")
        return FrontmostWindow(app_name="", window_title="")
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
        return FrontmostWindow(app_name=app, window_title=title)
    return FrontmostWindow(app_name="", window_title="")


class _NotificationDelegate(NSObject):
    """Handles notification click events."""

    def userNotificationCenter_didActivateNotification_(  # noqa: N802
        self,
        center: object,  # noqa: ARG002
        notification: NSUserNotification,  # noqa: ARG002
    ) -> None:
        user_info = notification.userInfo()
        if user_info and _focus_callback:
            pid = user_info.get("pid")
            if pid:
                _focus_callback(int(pid))

    def userNotificationCenter_shouldPresentNotification_(  # noqa: N802
        self,
        center: object,  # noqa: ARG002
        notification: NSUserNotification,  # noqa: ARG002
    ) -> bool:
        return True


# Singleton delegate — must stay alive for the lifetime of the app.
# Deferred to first NotificationService instantiation to avoid side effects at import.
_delegate: _NotificationDelegate | None = None


def _ensure_delegate() -> None:
    """Initialize the notification delegate on first use (not at import time)."""
    global _delegate  # noqa: PLW0603
    if _delegate is not None:
        return
    _delegate = _NotificationDelegate.alloc().init()
    center = NSUserNotificationCenter.defaultUserNotificationCenter()
    if center is not None:
        center.setDelegate_(_delegate)
    else:
        log.warning("NSUserNotificationCenter unavailable — notifications disabled")


class NotificationService(BaseService):
    """Sends native macOS notifications with click-to-focus."""

    def __init__(self) -> None:
        super().__init__()
        _ensure_delegate()
        self._notified_pids: set[int] = set()
        self.cooldown = 30.0
        self.last_notification_time = 0.0
        self._center = NSUserNotificationCenter.defaultUserNotificationCenter()

    def send(self, title: str, subtitle: str, message: str) -> None:
        """Send a single notification (fire-and-forget)."""
        if not features.is_enabled("notifications") or self._center is None:
            return
        n = NSUserNotification.alloc().init()
        n.setTitle_(title)
        n.setSubtitle_(subtitle)
        n.setInformativeText_(message[:200])
        self._center.deliverNotification_(n)

    def notify_if_needed(self, sessions: list[ClaudeSession]) -> None:  # noqa: PLR0912
        """Send notifications for sessions that need attention."""
        if not features.is_enabled("notifications"):
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

        front = _get_frontmost_window()
        new_attention = [s for s in new_attention if f" {s.project} " not in f" {front.window_title} "]
        if not new_attention:
            return

        self.last_notification_time = now

        for s in new_attention:
            title = "Claude needs attention"
            subtitle = s.project
            if s.prompt_text:
                message = s.prompt_text
            elif s.task_summary:
                message = s.task_summary
            elif s.last_output:
                message = s.last_output
            else:
                message = "Waiting for input"

            log.info(
                "notification.sent project=%s action=%s host=%s pid=%d",
                s.project,
                s.prompt_text or "permission",
                s.host_app.value,
                s.pid,
            )

            n = NSUserNotification.alloc().init()
            n.setTitle_(title)
            n.setSubtitle_(subtitle)
            n.setInformativeText_(message[:200])
            n.setHasActionButton_(True)
            n.setActionButtonTitle_("Focus")
            n.setUserInfo_({"pid": s.pid, "project": s.project})

            sound_name = str(features.get_facet("notifications", "sound") or "Glass")
            if sound_name:
                n.setSoundName_(sound_name)

            self._center.deliverNotification_(n)
            self._notified_pids.add(s.pid)

        live_attention_pids = {s.pid for s in attention}
        self._notified_pids &= live_attention_pids
