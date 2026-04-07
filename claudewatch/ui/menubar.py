import logging
import logging.handlers
import os
import re
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import Future, ThreadPoolExecutor

from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSMenu,
    NSMenuItem,
    NSPasteboard,
    NSPasteboardTypeString,
    NSStatusBar,
    NSTextField,
    NSTimer,
)
from PyObjCTools import AppHelper

import claudewatch.backend.core.login_item  # noqa: F401 — registers feature
from claudewatch.backend.analytics.dependencies import get_analytics_service
from claudewatch.backend.analytics.service import AnalyticsService
from claudewatch.backend.bookmark.dependencies import get_bookmark_service
from claudewatch.backend.bookmark.service import BookmarkService
from claudewatch.backend.core import features
from claudewatch.backend.core.helpers import escape_applescript, run_applescript
from claudewatch.backend.core.models import ClaudeSession
from claudewatch.backend.core.paths import LOG_PATH, ensure_data_dir
from claudewatch.backend.core.session_log.dependencies import get_session_log_service
from claudewatch.backend.core.settings import ensure_defaults_migrated, get_setting
from claudewatch.backend.detection.dependencies import get_detection_service
from claudewatch.backend.detection.service import DetectionService
from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.history.service import HistoryService
from claudewatch.backend.notifications.dependencies import get_notification_service
from claudewatch.backend.notifications.service import NotificationService, set_focus_callback
from claudewatch.backend.onboarding.dependencies import get_onboarding_service
from claudewatch.backend.onboarding.service import OnboardingService
from claudewatch.backend.security.dependencies import get_security_service
from claudewatch.backend.security.service import SecurityService
from claudewatch.backend.summary.dependencies import get_summary_service
from claudewatch.backend.summary.service import SummaryService
from claudewatch.backend.updates.dependencies import get_update_service
from claudewatch.backend.updates.service import UpdateService
from claudewatch.backend.usage.dependencies import get_usage_service
from claudewatch.backend.usage.service import UsageService
from claudewatch.ui.activity import show_activity
from claudewatch.ui.focus import focus_session
from claudewatch.ui.menu.core import AppDelegate, MenuCallback, make_menu_item
from claudewatch.ui.menu_builder import MenuBuilder
from claudewatch.ui.preferences import show_preferences
from claudewatch.ui.session_actions import clean_exit_session, is_accessibility_trusted, notify_paused
from claudewatch.ui.theme import theme
from claudewatch.ui.welcome import should_show_welcome, show_welcome

log = logging.getLogger("claudewatch")

# Background thread pool for detection (single worker — prevents overlapping polls)
_executor = ThreadPoolExecutor(max_workers=1)

_MAX_ERRORS = 10


class ClaudeWatchApp:
    def __init__(  # noqa: PLR0913
        self,
        delegate: AppDelegate,
        *,
        detection_service: DetectionService,
        summary_service: SummaryService,
        notification_service: NotificationService,
        onboarding_service: OnboardingService,
        update_service: UpdateService,
        usage_service: UsageService,
        bookmark_service: BookmarkService,
        history_service: HistoryService,
        analytics_service: AnalyticsService,
        security_service: SecurityService,
    ) -> None:
        self._delegate = delegate
        self._menu = NSMenu.alloc().init()
        self._menu.setAutoenablesItems_(False)
        self._status_item: object | None = None
        self.sessions: list[ClaudeSession] = []
        self._last_menu_key = "__uninitialized__"
        self._consecutive_errors = 0
        self._detection_service = detection_service
        self._summary_service = summary_service
        self._notification_service = notification_service
        self._onboarding_service = onboarding_service
        self._update_service = update_service
        self._usage_service = usage_service
        self._bookmark_service = bookmark_service
        self._history_service = history_service
        self._analytics_service = analytics_service
        self._security_service = security_service
        self._future: Future | None = None  # type: ignore[type-arg]
        self._last_poll_time = 0.0
        self._last_scan_time = 0.0
        self._last_security_check = 0.0
        self._scan_lock = threading.Lock()
        self._scan_running = False
        self._modal_active = False
        self._prev_pids: set[int] = set()
        self._prev_status: dict[int, str] = {}
        self._prev_sessions: dict[int, ClaudeSession] = {}
        self._exiting_pids: dict[int, float] = {}  # PID → time of quit signal
        self._has_polled = False
        self._check_accessibility()
        self._menu_builder = MenuBuilder(self, self._menu, delegate)
        # Run first detection synchronously so menu has data immediately
        try:
            self.sessions = self._detection_service.detect()
            self._has_polled = True
        except Exception:
            log.exception("initial detection failed")
        self.update_display()
        # Kick off background update check
        threading.Thread(target=self._update_service.check, daemon=True).start()
        threading.Thread(target=self._security_service.warm_command_cache, daemon=True).start()

    def run(self) -> None:
        """Start the app: create status bar item, timer, and run the event loop."""
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        status_bar = NSStatusBar.systemStatusBar()
        self._status_item = status_bar.statusItemWithLength_(-1)  # NSVariableStatusItemLength
        self._status_item.setMenu_(self._menu)
        self._status_item.setTitle_("")

        # Re-render now that _status_item exists
        self.update_display()

        # First-launch welcome window
        if should_show_welcome():
            show_welcome()

        # Poll timer — fires every 1s on the main run loop
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0,
            self._delegate,
            "pollTick:",
            None,
            True,
        )

        AppHelper.runEventLoop()

    def _log_changes(self) -> None:
        """Log meaningful events: new sessions, ended sessions, status changes.

        Debounces rapid status flickers (e.g. working→attention→working)
        by requiring a state to persist for 2+ poll cycles before logging.
        """
        current_pids = {s.pid for s in self.sessions}
        current_status = {s.pid: s.status.value for s in self.sessions}
        session_map = {s.pid: s for s in self.sessions}

        # New sessions (skip on first poll — don't log all existing sessions as "started")
        new_pids = current_pids - self._prev_pids
        if self._prev_pids:  # not first poll
            for pid in new_pids:
                s = session_map[pid]
                model = self._usage_service.get_model(s.cwd)
                log.info(
                    "session.started project=%s host=%s model=%s pid=%d",
                    s.project,
                    s.host_app.value,
                    model or "unknown",
                    pid,
                )

        # Track cumulative session count for onboarding "hover" tip
        if new_pids and not self._onboarding_service.is_tip_shown("hover"):
            self._onboarding_service.increment_session_count(len(new_pids))

        # Ended sessions — record to history
        for pid in self._prev_pids - current_pids:
            log.info("session.ended pid=%d", pid)
            prev = self._prev_sessions.get(pid)
            if prev:
                self._history_service.record(
                    session_id=prev.session_id,
                    project=prev.project,
                    cwd=prev.cwd,
                    model=self._usage_service.get_model(prev.cwd),
                    host_app=prev.host_app.value,
                )

        # No status transition logging — it's polling noise.
        # Meaningful events (notifications, pins, quits, resumes) are
        # logged where they happen.

        self._prev_pids = current_pids
        self._prev_status = current_status
        self._prev_sessions = session_map

    def _check_onboarding_tips(self) -> None:
        """Track session count for guide nudge (no notification tips)."""
        pass

    _INTERVAL_MAP = {"10s": 10, "30s": 30, "60s": 60, "5m": 300}

    def _run_security_checks(self) -> None:
        """Run throttled security config + runtime checks."""
        interval_str = str(features.get_facet("security", "check_interval") or "30s")
        interval = self._INTERVAL_MAP.get(interval_str, 30)
        now = time.time()
        if now - self._last_security_check < interval:
            return
        self._last_security_check = now
        try:
            config_alerts = self._security_service.check_config()
            runtime_alerts = self._security_service.check_runtime(self.sessions)
            all_alerts = config_alerts + runtime_alerts
            if all_alerts:
                self._security_service.process_alerts(all_alerts)
        except Exception:
            log.warning("security check failed", exc_info=True)

    _SCAN_INTERVAL = 30

    def _maybe_bg_scan(self) -> None:
        """Kick off an analytics scan if enough time has passed and none is running."""
        with self._scan_lock:
            if self._scan_running:
                return
            now = time.time()
            if now - self._last_scan_time < self._SCAN_INTERVAL:
                return
            self._last_scan_time = now
            self._scan_running = True
        threading.Thread(target=self._bg_scan, daemon=True).start()

    def _bg_scan(self) -> None:
        try:
            self._analytics_service.incremental_scan()
        except Exception:
            log.exception("analytics background scan failed")
        finally:
            with self._scan_lock:
                self._scan_running = False

    def _check_accessibility(self) -> None:
        """Show a warning if Accessibility permissions are not granted."""
        if not is_accessibility_trusted():
            log.warning("Accessibility permission not granted")
            self._accessibility_warning = True
        else:
            self._accessibility_warning = False

    def poll(self) -> None:
        if self._modal_active:
            return
        # Respect configurable poll interval (timer ticks every 1s, we skip until interval)
        now = time.time()
        interval = int(get_setting("poll_interval") or 3)
        if now - self._last_poll_time < interval:
            return
        self._last_poll_time = now

        # Recheck accessibility so warning dismisses after user grants it
        self._check_accessibility()

        # Collect results from background detection if ready
        if self._future is not None:
            if not self._future.done():
                return  # previous detection still running
            try:
                self.sessions = self._future.result()
                # Filter out sessions we've sent a quit signal to (grace period)
                _exit_grace = 10  # seconds
                now = time.time()
                self._exiting_pids = {p: t for p, t in self._exiting_pids.items() if now - t < _exit_grace}
                self.sessions = [s for s in self.sessions if s.pid not in self._exiting_pids]
                self._has_polled = True
                self._log_changes()
                self._analytics_service.enrich_sessions(self.sessions)
                self._maybe_bg_scan()
                self.update_display()
                self._notification_service.notify_if_needed(self.sessions)
                self._run_security_checks()
                self._check_onboarding_tips()
                self._consecutive_errors = 0
            except Exception:
                self._consecutive_errors += 1
                log.exception("poll error (%d)", self._consecutive_errors)
                if self._consecutive_errors >= _MAX_ERRORS:
                    self._status_item.setTitle_("⚠️ error")
                    self._menu.removeAllItems()
                    self._delegate._callbacks.clear()
                    self._delegate._next_tag = 1
                    self._menu.addItem_(make_menu_item("Too many errors — restart app", None, self._delegate))
                    self._menu.addItem_(NSMenuItem.separatorItem())
                    self._menu.addItem_(make_menu_item("Quit", self._quit, self._delegate))
            self._future = None

        # Dispatch new detection to background thread
        self._future = _executor.submit(self._detection_service.detect)

    def _menu_key(self) -> str:
        parts = [f"scheme:{theme.scheme.name}"]
        for s in self.sessions:
            cached = self._summary_service.get_cached(s.cwd) or ""
            parts.append(f"{s.pid}:{s.status.value}:{s.project}:{s.task_summary}:{s.last_output}:{cached}")
        return "|".join(parts)

    def update_display(self) -> None:
        self._menu_builder.build(self.sessions)

    def _make_activity_handler(self, session: ClaudeSession) -> MenuCallback:
        project = session.project
        cwd = session.cwd

        def handler(_: NSMenuItem) -> None:
            show_activity(project, cwd, session_active=True)

        return handler

    def _make_click_handler(self, session: ClaudeSession) -> MenuCallback:
        pid = session.pid

        def handler(_: NSMenuItem) -> None:
            try:
                current = next((s for s in self.sessions if s.pid == pid), session)
                focus_session(current)
            except Exception:
                log.exception("focus error")

        return handler

    def _make_bookmark_handler(self, session: ClaudeSession) -> MenuCallback:  # noqa: PLR0915
        sid = session.session_id
        project = session.project
        cwd = session.cwd
        pid = session.pid
        tty = session.tty
        wid = session.window_id

        def handler(_: NSMenuItem) -> None:
            self._modal_active = True
            try:
                app = NSApplication.sharedApplication()
                app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
                app.activateIgnoringOtherApps_(True)

                alert = NSAlert.alloc().init()
                alert.setMessageText_("Bookmark Session")
                alert.setInformativeText_(f"Add a note for {project}:")
                alert.addButtonWithTitle_("Bookmark")
                alert.addButtonWithTitle_("Generate Summary")
                alert.addButtonWithTitle_("Cancel")
                text_field = NSTextField.alloc().initWithFrame_(((0, 0), (350, 60)))
                text_field.setStringValue_("")
                text_field.setPlaceholderString_("Add a note…")
                text_field.setLineBreakMode_(0)  # NSLineBreakByWordWrapping
                text_field.setUsesSingleLineMode_(False)
                alert.setAccessoryView_(text_field)
                alert.window().setInitialFirstResponder_(text_field)

                modal_dismissed = threading.Event()

                def _fill_summary() -> None:
                    summary = self._summary_service.generate_and_cache(cwd)
                    if summary and not modal_dismissed.is_set():
                        text_field.performSelectorOnMainThread_withObject_waitUntilDone_(
                            "setStringValue:",
                            summary,
                            True,
                        )

                _second_btn = 1001

                result = alert.runModal()
                if result == _second_btn:
                    # Generate Summary clicked — fill and re-show
                    text_field.setStringValue_("Generating…")
                    threading.Thread(target=_fill_summary, daemon=True).start()
                    result = alert.runModal()

                modal_dismissed.set()
                if result == NSAlertFirstButtonReturn:
                    note = str(text_field.stringValue()).strip()
                    self._bookmark_service.add(sid, project, cwd, note)
                    if note:
                        self._summary_service.cache(cwd, note)

                    quit_alert = NSAlert.alloc().init()
                    quit_alert.setMessageText_("Quit this session?")
                    quit_alert.setInformativeText_(f"Cleanly exit {project}?\nResume later from the Pinned section.")
                    quit_alert.addButtonWithTitle_("Quit Session")
                    quit_alert.addButtonWithTitle_("Keep Running")
                    if quit_alert.runModal() == NSAlertFirstButtonReturn:
                        clean_exit_session(tty, pid, project, wid)
                        self._exiting_pids[pid] = time.time()
            finally:
                self._modal_active = False
                self._last_menu_key = ""
                self.update_display()

        return handler

    def _make_quit_handler(self, session: ClaudeSession) -> MenuCallback:
        pid = session.pid
        project = session.project
        cwd = session.cwd
        tty = session.tty
        wid = session.window_id
        pinned = cwd in self._bookmark_service.get_bookmarked_cwds()

        def handler(_: NSMenuItem) -> None:
            exited = False
            if pinned:
                clean_exit_session(tty, pid, project, wid)
                self._exiting_pids[pid] = time.time()
                exited = True
                notify_paused(project)
            else:
                self._modal_active = True
                try:
                    app = NSApplication.sharedApplication()
                    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
                    app.activateIgnoringOtherApps_(True)
                    alert = NSAlert.alloc().init()
                    alert.setMessageText_(f"Quit {project}?")
                    alert.setInformativeText_("This will cleanly exit the Claude session.")
                    alert.addButtonWithTitle_("Quit")
                    alert.addButtonWithTitle_("Cancel")
                    if alert.runModal() == NSAlertFirstButtonReturn:
                        clean_exit_session(tty, pid, project, wid)
                        self._exiting_pids[pid] = time.time()
                        exited = True
                finally:
                    self._modal_active = False
            if exited:
                threading.Thread(target=self._summary_service.generate_and_cache, args=(cwd,), daemon=True).start()
            self._last_menu_key = ""
            self.update_display()

        return handler

    def _make_unbookmark_handler(self, cwd: str) -> MenuCallback:
        def handler(_: NSMenuItem) -> None:
            self._modal_active = True
            try:
                app = NSApplication.sharedApplication()
                app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
                app.activateIgnoringOtherApps_(True)
                alert = NSAlert.alloc().init()
                alert.setMessageText_("Unpin this session?")
                alert.setInformativeText_("You can always pin it again later.")
                alert.addButtonWithTitle_("Unpin")
                alert.addButtonWithTitle_("Cancel")
                if alert.runModal() == NSAlertFirstButtonReturn:
                    self._bookmark_service.remove(cwd)
            finally:
                self._modal_active = False
                self._last_menu_key = ""
                self.update_display()

        return handler

    def _make_resume_handler(self, session_id: str, cwd: str = "") -> MenuCallback:
        def handler(_: NSMenuItem) -> None:
            # Validate session ID is a UUID to prevent command injection
            if not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", session_id):
                log.warning("invalid session ID: %s", session_id[:20])
                return
            # Verify the session JSONL still exists before trying to resume
            path = get_session_log_service().find_most_recent(cwd) if cwd else None
            if not path:
                log.warning("session JSONL not found for resume: %s", session_id[:8])
                return
            # Open a new Terminal tab, cd to the project dir, and resume
            safe_cwd = escape_applescript(cwd) if cwd else ""
            cd_cmd = f'cd \\"{safe_cwd}\\" && ' if safe_cwd else ""
            run_applescript(f"""
                tell application "Terminal"
                    activate
                    do script "{cd_cmd}claude -r {session_id}"
                end tell
            """)
            log.info("session resumed: %s", session_id[:8])

        return handler

    def _make_history_activity_handler(self, project: str, cwd: str) -> MenuCallback:
        def handler(_: NSMenuItem) -> None:
            show_activity(project, cwd)

        return handler

    def _make_remove_history_handler(self, cwd: str) -> MenuCallback:
        def handler(_: NSMenuItem) -> None:
            self._history_service.remove(cwd)
            self._last_menu_key = ""
            self.update_display()

        return handler

    def _make_open_update_handler(self) -> MenuCallback:
        def handler(_: NSMenuItem) -> None:
            update_info = self._update_service.get_cached()
            if not update_info:
                return
            tag = update_info.tag

            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            app.activateIgnoringOtherApps_(True)
            alert = NSAlert.alloc().init()
            alert.setMessageText_(f"Update to {tag}?")
            alert.setInformativeText_("ClaudeWatch will download the update, quit, and relaunch automatically.")
            alert.addButtonWithTitle_("Update")
            alert.addButtonWithTitle_("Cancel")
            if alert.runModal() != NSAlertFirstButtonReturn:
                return

            def quit_app() -> None:
                AppHelper.stopEventLoop()

            success = self._update_service.download_and_apply(tag, on_ready=quit_app)
            if not success:
                # Fallback: open browser
                webbrowser.open("https://github.com/wingatethomas/claudewatch/releases/latest")

        return handler

    def _copy_brew_update(self, _: NSMenuItem) -> None:
        """Copy the brew upgrade command to clipboard."""
        cmd = "brew upgrade --cask claudewatch"
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(cmd, NSPasteboardTypeString)

        update_info = self._update_service.get_cached()
        tag = update_info.tag if update_info else ""
        app = NSApplication.sharedApplication()
        app.activateIgnoringOtherApps_(True)
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"Update to {tag}")
        alert.setInformativeText_(f"Copied to clipboard:\n\n{cmd}\n\nPaste this in your terminal to update.")
        alert.addButtonWithTitle_("OK")
        alert.runModal()

    def _open_accessibility(self, _: NSMenuItem) -> None:
        """Open System Settings to the Accessibility pane."""
        subprocess.run(  # noqa: S603, S607
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            check=False,
        )
        self._check_accessibility()

    def _open_preferences(self, _: NSMenuItem) -> None:
        show_preferences()

    def _open_guide(self, _: NSMenuItem) -> None:
        self._onboarding_service._mark_shown("guide_nudge")
        show_preferences(pane="guide")

    def _dismiss_guide(self, _: NSMenuItem) -> None:
        self._onboarding_service._mark_shown("guide_nudge")
        self._last_menu_key = ""  # force menu rebuild

    def _open_github(self, _: NSMenuItem) -> None:
        webbrowser.open("https://github.com/wingatethomas/claudewatch")

    def _restart(self, _: NSMenuItem) -> None:
        log.info("app.restart")
        # Remove the status bar item before replacing the process,
        # otherwise the old icon lingers in the menu bar
        if self._status_item is not None:
            NSStatusBar.systemStatusBar().removeStatusItem_(self._status_item)
            self._status_item = None
        AppHelper.stopEventLoop()
        os.execv(sys.executable, [sys.executable] + sys.argv)  # noqa: S606

    def _quit(self, _: NSMenuItem) -> None:
        log.info("app.quit")
        AppHelper.stopEventLoop()


def main() -> None:
    """Entry point for the claudewatch command."""
    # No console output — all logging goes to the audit file only
    logger = logging.getLogger("claudewatch")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # prevent root logger from printing to stderr

    ensure_data_dir()
    ensure_defaults_migrated()
    if not os.path.exists(LOG_PATH):
        os.open(LOG_PATH, os.O_CREAT | os.O_WRONLY, 0o600)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH,
        maxBytes=1_000_000,
        backupCount=3,
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    logger.addHandler(file_handler)

    def _sigint_handler(*_args: object) -> None:
        log.info("app.sigint")
        os._exit(0)  # noqa: SLF001

    signal.signal(signal.SIGINT, _sigint_handler)

    delegate = AppDelegate.alloc().init()
    app = ClaudeWatchApp(
        delegate,
        detection_service=get_detection_service(),
        summary_service=get_summary_service(),
        notification_service=get_notification_service(),
        onboarding_service=get_onboarding_service(),
        update_service=get_update_service(),
        usage_service=get_usage_service(),
        bookmark_service=get_bookmark_service(),
        history_service=get_history_service(),
        analytics_service=get_analytics_service(),
        security_service=get_security_service(),
    )
    delegate._app = app

    # Wire notification click → focus session
    def _on_notification_click(pid: int) -> None:
        session = next((s for s in app.sessions if s.pid == pid), None)
        if session:
            focus_session(session)

    set_focus_callback(_on_notification_click)
    app.run()
