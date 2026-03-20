"""Native macOS notifications via NSUserNotificationCenter.

Requires an Info.plist with CFBundleIdentifier next to sys.executable —
created automatically by ensure_info_plist().
"""

import logging
import os
import subprocess
import sys
import time

from Foundation import NSDate, NSMutableDictionary, NSUserNotification, NSUserNotificationCenter
from rumps._internal import string_to_objc
from rumps.rumps import App as RumpsApp
from rumps.rumps import NSApp as RumpsNSApp

from claudewatch.backend.helpers import escape_applescript, run_applescript
from claudewatch.backend.models import ClaudeSession, HostApp
from claudewatch.backend.repositories.config import get_setting

log = logging.getLogger("claudewatch")

_BUNDLE_ID = "com.claudewatch.app"


def ensure_info_plist() -> bool:
    """Create Info.plist next to sys.executable if missing.

    NSUserNotificationCenter requires a CFBundleIdentifier to deliver
    notifications. Without this, defaultUserNotificationCenter() returns None.
    """
    plist_dir = os.path.dirname(sys.executable)
    plist_path = os.path.join(plist_dir, "Info.plist")
    if os.path.exists(plist_path):
        return True
    try:
        subprocess.run(  # noqa: S603, S607
            ["/usr/libexec/PlistBuddy", "-c", f"Add :CFBundleIdentifier string {_BUNDLE_ID}", plist_path],
            check=True,
            capture_output=True,
        )
        log.info("Created Info.plist at %s", plist_path)
        return True
    except (subprocess.CalledProcessError, OSError) as e:
        log.warning("Failed to create Info.plist: %s", e)
        return False


def install_notification_delegate() -> None:
    """Patch rumps delegate to always show notifications, even when app is active."""
    def _should_present(self, center, notification):  # noqa: ANN001, ANN202, ARG001
        return True

    RumpsNSApp.userNotificationCenter_shouldPresentNotification_ = _should_present


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


def _build_focus_data(s: ClaudeSession) -> dict:
    """Build data dict for the notification click callback."""
    data: dict = {"pid": s.pid, "project": s.project, "host_app": s.host_app.value}
    if s.host_app == HostApp.TERMINAL and s.window_id is not None:
        data["window_id"] = s.window_id
    return data


def handle_notification_click(data: dict) -> None:
    """Focus the session window when a notification is clicked."""
    host_app = data.get("host_app", "")
    project = data.get("project", "")

    if host_app == HostApp.TERMINAL.value and "window_id" in data:
        wid = data["window_id"]
        # window_id is always int — validated via isdigit() in detection.py
        run_applescript(f"""
            tell application "Terminal"
                set index of window id {wid} to 1
            end tell
            tell application "System Events"
                tell process "Terminal"
                    perform action "AXRaise" of first window
                    set frontmost to true
                end tell
            end tell
        """)
    elif host_app == HostApp.PYCHARM.value:
        safe_project = escape_applescript(project)
        run_applescript(
            f'tell application "System Events" to tell process "pycharm"'
            f' to perform action "AXRaise" of first window whose name contains "{safe_project}"',
        )
    elif host_app == HostApp.VSCODE.value:
        safe_project = escape_applescript(project)
        run_applescript(
            f'tell application "System Events" to tell process "Code"'
            f' to perform action "AXRaise" of first window whose name contains "{safe_project}"',
        )


def _send_notification(  # noqa: PLR0913
    title: str,
    subtitle: str,
    message: str,
    sound_name: str,
    group_id: str,
    data: dict | None = None,
) -> bool:
    """Send a native macOS notification. Returns True on success."""
    nc = NSUserNotificationCenter.defaultUserNotificationCenter()
    if nc is None:
        log.warning("NSUserNotificationCenter unavailable (missing Info.plist?)")
        return False

    n = NSUserNotification.alloc().init()
    n.setTitle_(title)
    n.setSubtitle_(subtitle)
    n.setInformativeText_(message)
    n.setIdentifier_(group_id)

    if sound_name and sound_name.lower() != "none":
        n.setSoundName_(sound_name)

    # Attach focus data for click callback — rumps deserializes from userInfo
    if data is not None:
        try:
            app_instance = getattr(RumpsApp, "*app_instance", None)
            if app_instance and hasattr(app_instance, "serializer"):
                dumped = app_instance.serializer.dumps(data)
                ns_dict = NSMutableDictionary.alloc().init()
                ns_dict.setObject_forKey_(string_to_objc(dumped), "value")
                n.setUserInfo_(ns_dict)
        except Exception:
            log.debug("Could not attach click data to notification")

    n.setDeliveryDate_(NSDate.dateWithTimeInterval_sinceDate_(0, NSDate.date()))
    nc.scheduleNotification_(n)
    return True


class NotificationManager:
    def __init__(self) -> None:
        self._notified_pids: set[int] = set()
        self.cooldown = 30.0
        self.last_notification_time = 0.0

    def notify_if_needed(self, sessions: list[ClaudeSession]) -> None:
        if not get_setting("notifications_enabled"):
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

            sent = _send_notification(
                title=title,
                subtitle=subtitle,
                message=message[:200],
                sound_name=str(get_setting("notification_sound")),
                group_id=f"claudewatch-{s.pid}",
                data=_build_focus_data(s),
            )
            if sent:
                self._notified_pids.add(s.pid)

        live_attention_pids = {s.pid for s in attention}
        self._notified_pids &= live_attention_pids
