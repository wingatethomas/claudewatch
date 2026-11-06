"""macOS notifications via NSUserNotificationCenter.

Uses the native (deprecated but functional) NSUserNotification API.
Handles click actions to focus the session window.
"""

import logging
import time

from Foundation import NSObject, NSUserNotification, NSUserNotificationCenter

from claudewatch.backend.core import features
from claudewatch.backend.core.features import FeatureKey
from claudewatch.backend.core.helpers import is_accessibility_trusted, run_applescript
from claudewatch.backend.core.models import ClaudeSession, SessionStatus
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
        self._finished_notified_pids: set[int] = set()
        self._working_seen_pids: set[int] = set()
        self.cooldown = 10.0
        self.last_notification_time = 0.0
        self._center = NSUserNotificationCenter.defaultUserNotificationCenter()

    def send(self, title: str, subtitle: str, message: str, *, sound: str | None = None) -> None:
        """Send a single notification (fire-and-forget)."""
        if not features.is_enabled(FeatureKey.NOTIFICATIONS) or self._center is None:
            return
        n = NSUserNotification.alloc().init()
        n.setTitle_(title)
        n.setSubtitle_(subtitle)
        n.setInformativeText_(message[:200])
        if sound:
            n.setSoundName_(sound)
        self._center.deliverNotification_(n)

    def notify_if_needed(self, sessions: list[ClaudeSession]) -> None:
        """Send notifications for sessions that need attention or just finished."""
        if not features.is_enabled(FeatureKey.NOTIFICATIONS):
            return
        self._notify_attention(sessions)
        self._notify_finished(sessions)

    def _notify_attention(self, sessions: list[ClaudeSession]) -> None:  # noqa: PLR0912
        attention = [s for s in sessions if s.needs_attention]

        # Evict PIDs that are no longer in ATTENTION — allows re-notification
        # when a session leaves ATTENTION (WORKING) and returns (ATTENTION again)
        attention_pids = {s.pid for s in attention}
        self._notified_pids &= attention_pids

        if not attention:
            return

        new_attention = [s for s in attention if s.pid not in self._notified_pids]
        if not new_attention:
            return

        now = time.time()
        if now - self.last_notification_time < self.cooldown:
            return

        self.last_notification_time = now

        for s in new_attention:
            # Privacy: notifications carry only the tool name + project name.
            # prompt_text from detection is shaped "ToolName: <input snippet>" — drop the snippet.
            tool_name = s.prompt_text.split(":", 1)[0].strip() if s.prompt_text else ""
            title = "Claude needs attention"
            subtitle = s.project
            message = f"{tool_name} approval needed" if tool_name else "Waiting for input"

            log.info(
                "notification.sent project=%s tool=%s host=%s pid=%d",
                s.project,
                tool_name or "permission",
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

            sound_name = str(features.get_facet(FeatureKey.NOTIFICATIONS, "sound") or "Glass")
            if sound_name:
                n.setSoundName_(sound_name)

            self._center.deliverNotification_(n)
            self._notified_pids.add(s.pid)

    def _notify_finished(self, sessions: list[ClaudeSession]) -> None:
        """Notify once when an auto-mode session completes a true WORKING→IDLE edge."""
        if self._center is None:
            return
        live_pids = {s.pid for s in sessions}
        self._working_seen_pids &= live_pids
        finished_pids = {s.pid for s in sessions if s.just_finished}
        self._finished_notified_pids &= finished_pids
        new_finished = [
            s
            for s in sessions
            if s.just_finished and s.pid in self._working_seen_pids and s.pid not in self._finished_notified_pids
        ]
        self._working_seen_pids |= {s.pid for s in sessions if s.status == SessionStatus.WORKING}
        if not new_finished:
            return

        now = time.time()
        if now - self.last_notification_time < self.cooldown:
            # Not marked notified — retried on the next poll once the cooldown clears.
            return
        self.last_notification_time = now

        for s in new_finished:
            log.info("notification.finished project=%s pid=%d", s.project, s.pid)
            n = NSUserNotification.alloc().init()
            n.setTitle_("Claude finished")
            n.setSubtitle_(s.project)
            n.setInformativeText_("Task complete")
            n.setHasActionButton_(True)
            n.setActionButtonTitle_("Focus")
            n.setUserInfo_({"pid": s.pid, "project": s.project})
            sound_name = str(features.get_facet(FeatureKey.NOTIFICATIONS, "sound") or "Glass")
            if sound_name:
                n.setSoundName_(sound_name)
            self._center.deliverNotification_(n)
            self._finished_notified_pids.add(s.pid)
            self._working_seen_pids.discard(s.pid)
