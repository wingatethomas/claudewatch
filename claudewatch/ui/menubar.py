import ctypes
import logging
import logging.handlers
import os
import re
import signal
import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor

import rumps
from AppKit import (
    NSApplication,
    NSBezierPath,
    NSColor,
    NSFont,
    NSImage,
    NSMutableAttributedString,
    NSPasteboard,
    NSString,
    NSStringPboardType,
    NSWorkspace,
)
from Foundation import NSMakeRect, NSMakeSize, NSRange

from claudewatch.backend.models import (
    HOST_APP_PATH,
    ClaudeSession,
    HostApp,
    SessionStatus,
)
from claudewatch.backend.repositories.bookmarks import get_bookmarks, remove_bookmark, save_bookmark
from claudewatch.backend.repositories.config import get_setting
from claudewatch.backend.services.detection import detect_sessions
from claudewatch.backend.services.notifications import (
    NotificationManager,
    ensure_info_plist,
    handle_notification_click,
    install_notification_delegate,
)
from claudewatch.ui.focus import focus_session
from claudewatch.ui.preferences import show_preferences

log = logging.getLogger("claudewatch")

# Background thread pool for detection (single worker — prevents overlapping polls)
_executor = ThreadPoolExecutor(max_workers=1)

# Status colors — the Digital Color Meter samples were display-rendered values,
# not sRGB input. Use brighter sRGB values that render to match Claude Code on screen.
_STATUS_COLORS = {
    SessionStatus.ATTENTION: NSColor.colorWithSRGBRed_green_blue_alpha_(0.85, 0.30, 0.28, 1.0),  # warm red
    SessionStatus.WORKING: NSColor.colorWithSRGBRed_green_blue_alpha_(0.25, 0.65, 0.30, 1.0),  # forest green
    SessionStatus.IDLE: NSColor.colorWithSRGBRed_green_blue_alpha_(0.85, 0.65, 0.15, 1.0),  # warm amber
}

# Cache for scaled NSImage icons
_app_icon_cache: dict[HostApp, NSImage | None] = {}

# Cache for status dot images
_status_dot_cache: dict[SessionStatus, NSImage] = {}


def _make_header_title(text: str, status: SessionStatus, count: int) -> NSMutableAttributedString:
    """Create an attributed string like '⚠ Needs Attention (3)  •••' with small colored dots."""
    dots = "●" * count
    full = f"{text} ({count})  {dots}"
    attr_str = NSMutableAttributedString.alloc().initWithString_(full)
    # Style the dots: colored, smaller font, baseline-shifted up to center vertically
    dot_start = len(full) - len(dots)
    dot_range = NSRange(dot_start, len(dots))
    color = _STATUS_COLORS.get(status, NSColor.secondaryLabelColor())
    attr_str.addAttribute_value_range_("NSColor", color, dot_range)
    attr_str.addAttribute_value_range_("NSFont", NSFont.systemFontOfSize_(7.0), dot_range)
    attr_str.addAttribute_value_range_("NSBaselineOffset", 2.0, dot_range)
    return attr_str


def _render_dot_row(status: SessionStatus, count: int) -> NSImage:
    """Render a row of colored dots as an NSImage for section headers."""
    _dot_diameter = 6.0
    _dot_gap = 3.0
    _dot_step = _dot_diameter + _dot_gap
    _height = 12.0

    width = max(count * _dot_step - _dot_gap, 1)
    img = NSImage.alloc().initWithSize_(NSMakeSize(width, _height))
    img.lockFocus()
    try:
        color = _STATUS_COLORS.get(status, NSColor.secondaryLabelColor())
        color.set()
        center_y = (_height - _dot_diameter) / 2.0
        for i in range(count):
            x = i * _dot_step
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(x, center_y, _dot_diameter, _dot_diameter),
            ).fill()
    finally:
        img.unlockFocus()
    img.setTemplate_(False)
    return img


def _render_status_icon(  # noqa: PLR0914
    attention: list[ClaudeSession],
    working: list[ClaudeSession],
    idle: list[ClaudeSession],
) -> NSImage:
    """Render a menu bar icon: ✦ symbol + colored dots (max 12, 2 rows of 4+)."""
    _dot_radius = 2.0
    _dot_gap = 2.0
    _dot_step = _dot_radius * 2 + _dot_gap
    _dots_per_row = 4
    _row_height = 7.0
    _symbol_width = 18.0
    _icon_height = 18.0
    _max_dots = 12

    # Build dot list: attention first (red), then working (green), then idle (yellow)
    dots: list[NSColor] = []
    for _ in attention:
        dots.append(_STATUS_COLORS[SessionStatus.ATTENTION])
    for _ in working:
        dots.append(_STATUS_COLORS[SessionStatus.WORKING])
    for _ in idle:
        dots.append(_STATUS_COLORS[SessionStatus.IDLE])
    dots = dots[:_max_dots]

    n_dots = len(dots)
    two_rows = n_dots > _dots_per_row
    cols = min(n_dots, _dots_per_row)
    dots_width = cols * _dot_step - _dot_gap if cols else 0
    width = _symbol_width + dots_width + 2.0

    img = NSImage.alloc().initWithSize_(NSMakeSize(width, _icon_height))
    img.lockFocus()
    try:
        # Draw ✦ symbol
        attrs = {
            "NSFont": NSFont.systemFontOfSize_(15.0),
            "NSColor": NSColor.labelColor(),
        }
        symbol = NSString.stringWithString_("✦")
        symbol.drawAtPoint_withAttributes_((0.0, 0.0), attrs)

        # Draw dots in a grid — 1 or 2 rows
        if two_rows:
            top_y = _icon_height / 2.0 + 1.0
            bot_y = top_y - _row_height
        else:
            top_y = _icon_height / 2.0 - _dot_radius + 1.0
            bot_y = top_y  # unused

        for i, color in enumerate(dots):
            col = i % _dots_per_row
            row_y = top_y if i < _dots_per_row else bot_y
            x = _symbol_width + col * _dot_step
            color.set()
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(x, row_y, _dot_radius * 2, _dot_radius * 2),
            ).fill()
    finally:
        img.unlockFocus()
    img.setTemplate_(False)
    return img


def _get_app_icon(app: HostApp, size: int = 16) -> NSImage | None:
    """Get the actual macOS app icon, scaled to menu size. Cached."""
    if app in _app_icon_cache:
        return _app_icon_cache[app]
    path = HOST_APP_PATH.get(app)
    if not path:
        _app_icon_cache[app] = None
        return None
    icon = NSWorkspace.sharedWorkspace().iconForFile_(path)
    if icon:
        icon = icon.copy()
        icon.setSize_((size, size))
    _app_icon_cache[app] = icon
    return icon


def _is_accessibility_trusted() -> bool:
    """Check if the app has Accessibility permissions via AXIsProcessTrusted."""
    try:
        lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return lib.AXIsProcessTrusted()
    except OSError:
        return False


_MAX_ERRORS = 10


class ClaudeWatchApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("ClaudeWatch", quit_button=None)
        self.sessions: list[ClaudeSession] = []
        self._last_menu_key = ""
        self._consecutive_errors = 0
        self.icon = None
        self.notifications = NotificationManager()
        self._future: Future | None = None  # type: ignore[type-arg]
        self._last_poll_time = 0.0
        self._modal_active = False
        self._prev_pids: set[int] = set()
        self._prev_status: dict[int, str] = {}
        self._check_accessibility()
        self.update_display()

    def _log_changes(self) -> None:
        """Log only meaningful events: new sessions, ended sessions, status changes."""
        current_pids = {s.pid for s in self.sessions}
        current_status = {s.pid: s.status.value for s in self.sessions}
        session_map = {s.pid: s for s in self.sessions}

        # New sessions
        for pid in current_pids - self._prev_pids:
            s = session_map[pid]
            log.info("session started: project=%s host=%s pid=%d", s.project, s.host_app.value, pid)

        # Ended sessions
        for pid in self._prev_pids - current_pids:
            log.info("session ended: pid=%d", pid)

        # Status changes
        for pid in current_pids & self._prev_pids:
            old = self._prev_status.get(pid)
            new = current_status[pid]
            if old and old != new:
                s = session_map[pid]
                log.info("status change: project=%s %s -> %s pid=%d", s.project, old, new, pid)

        self._prev_pids = current_pids
        self._prev_status = current_status

    def _check_accessibility(self) -> None:
        """Show a warning if Accessibility permissions are not granted."""
        if not _is_accessibility_trusted():
            log.warning("Accessibility permission not granted")
            self._accessibility_warning = True
        else:
            self._accessibility_warning = False

    @rumps.timer(1)
    def poll(self, _: rumps.Timer) -> None:
        if self._modal_active:
            return
        # Respect configurable poll interval (timer ticks every 1s, we skip until interval)
        now = time.time()
        interval = int(get_setting("poll_interval") or 3)
        if now - self._last_poll_time < interval:
            return
        self._last_poll_time = now

        # Collect results from background detection if ready
        if self._future is not None:
            if not self._future.done():
                return  # previous detection still running
            try:
                self.sessions = self._future.result()
                self._log_changes()
                self.update_display()
                self.notifications.notify_if_needed(self.sessions)
                self._consecutive_errors = 0
            except Exception:
                self._consecutive_errors += 1
                log.exception("poll error (%d)", self._consecutive_errors)
                if self._consecutive_errors >= _MAX_ERRORS:
                    self.title = "⚠️ error"
                    self.menu.clear()
                    self.menu.add(rumps.MenuItem("Too many errors — restart app", callback=None))
                    self.menu.add(rumps.separator)
                    self.menu.add(rumps.MenuItem("Quit", callback=self._quit))
            self._future = None

        # Dispatch new detection to background thread
        self._future = _executor.submit(detect_sessions)

    def _menu_key(self) -> str:
        return "|".join(f"{s.pid}:{s.status.value}:{s.project}:{s.task_summary}:{s.last_output}" for s in self.sessions)

    def update_display(self) -> None:  # noqa: PLR0912, PLR0915
        attention = [s for s in self.sessions if s.status == SessionStatus.ATTENTION]
        working = [s for s in self.sessions if s.status == SessionStatus.WORKING]
        idle = [s for s in self.sessions if s.status == SessionStatus.IDLE]

        # Menu bar icon — ✦ with colored dots for each state
        status_icon = _render_status_icon(attention, working, idle)
        if hasattr(self, "_nsapp") and self._nsapp is not None:
            self._nsapp.nsstatusitem.setImage_(status_icon)
        self.title = ""

        key = self._menu_key()
        if key == self._last_menu_key:
            return
        self._last_menu_key = key

        self.menu.clear()

        # App title
        app_title = rumps.MenuItem("ClaudeWatch", callback=None)
        self.menu.add(app_title)
        self.menu.add(rumps.separator)

        # Show accessibility warning if needed
        if self._accessibility_warning:
            warn = rumps.MenuItem("⚠️ Grant Accessibility in System Settings", callback=self._open_accessibility)
            self.menu.add(warn)
            self.menu.add(rumps.separator)

        if not self.sessions:
            self.menu.add(rumps.MenuItem("No active Claude sessions", callback=None))
        else:
            # Build suffix map to disambiguate duplicate labels
            seen_labels: dict[str, int] = {}
            suffixes: dict[int, str] = {}
            for s in self.sessions:
                label = s.menu_label
                seen_labels[label] = seen_labels.get(label, 0) + 1
            label_counters: dict[str, int] = {}
            for s in self.sessions:
                label = s.menu_label
                if seen_labels[label] > 1:
                    label_counters[label] = label_counters.get(label, 0) + 1
                    suffixes[s.pid] = f" #{label_counters[label]}"
                else:
                    suffixes[s.pid] = ""

            if attention:
                header = rumps.MenuItem("⚠ Needs Attention")
                header.set_callback(None)
                header._menuitem.setAttributedTitle_(
                    _make_header_title("⚠ Needs Attention", SessionStatus.ATTENTION, len(attention)),
                )
                self.menu.add(header)
                for s in attention:
                    self._add_session_items(s, suffixes[s.pid])

            if attention and (working or idle):
                self.menu.add(rumps.separator)

            if working:
                header = rumps.MenuItem("✦ Working")
                header.set_callback(None)
                header._menuitem.setAttributedTitle_(
                    _make_header_title("✦ Working", SessionStatus.WORKING, len(working)),
                )
                self.menu.add(header)
                for s in working:
                    self._add_session_items(s, suffixes[s.pid])

            if working and idle:
                self.menu.add(rumps.separator)

            if idle:
                header = rumps.MenuItem("⏸ Idle")
                header.set_callback(None)
                header._menuitem.setAttributedTitle_(
                    _make_header_title("⏸ Idle", SessionStatus.IDLE, len(idle)),
                )
                self.menu.add(header)
                for s in idle:
                    self._add_session_items(s, suffixes[s.pid])

        # Saved sessions
        saved = get_bookmarks()
        if saved:
            self.menu.add(rumps.separator)
            saved_header = rumps.MenuItem(f"Saved ({len(saved)})")
            saved_header.set_callback(None)
            self.menu.add(saved_header)
            for entry in saved:
                sid = entry.get("session_id", "")
                proj = entry.get("project", "unknown")
                note = entry.get("note", "")
                cwd = entry.get("cwd", "")
                ts = entry.get("timestamp", "")
                label = f"  {proj}"
                if note:
                    label += f" — {note}"
                item = rumps.MenuItem(label, callback=self._make_resume_handler(sid, cwd))
                item.add(rumps.MenuItem("Remove", callback=self._make_remove_saved_handler(sid)))
                self.menu.add(item)
                # Detail: CWD + saved time
                detail_parts = []
                if cwd:
                    detail_parts.append(cwd)
                if ts:
                    detail_parts.append(ts[:16].replace("T", " "))
                if detail_parts:
                    detail = rumps.MenuItem(f"      {' · '.join(detail_parts)}")
                    detail.set_callback(None)
                    self.menu.add(detail)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Preferences...", callback=self._open_preferences))
        self.menu.add(rumps.MenuItem("Quit", callback=self._quit))

    def _add_session_items(self, s: ClaudeSession, suffix: str = "") -> None:
        """Add a session entry + detail line to the menu."""
        label = s.menu_label + suffix
        # Main item — click to focus
        item = rumps.MenuItem(label, callback=self._make_click_handler(s))
        icon = _get_app_icon(s.host_app)
        if icon:
            item._menuitem.setImage_(icon)
        # Save sub-item nested under the session
        if s.session_id:
            save_item = rumps.MenuItem("Save session...", callback=self._make_save_handler(s))
            item.add(save_item)
        self.menu.add(item)
        detail = s.detail_line
        if detail:
            detail_item = rumps.MenuItem(f"      {detail}")
            detail_item.set_callback(None)
            self.menu.add(detail_item)

    def _make_click_handler(self, session: ClaudeSession):  # noqa: ANN202
        pid = session.pid

        def handler(_: rumps.MenuItem) -> None:
            try:
                current = next((s for s in self.sessions if s.pid == pid), session)
                focus_session(current)
            except Exception:
                log.exception("focus error")

        return handler

    def _make_save_handler(self, session: ClaudeSession):  # noqa: ANN202
        sid = session.session_id
        project = session.project
        cwd = session.cwd
        pid = session.pid

        def handler(_: rumps.MenuItem) -> None:
            self._modal_active = True
            try:
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                w = rumps.Window(
                    message=f"Add a note for {project}:",
                    title="Save Session",
                    default_text="",
                    ok="Save",
                    cancel="Cancel",
                    dimensions=(300, 24),
                )
                response = w.run()
                if response.clicked:
                    save_bookmark(sid, project, cwd, response.text.strip())
                    quit_response = rumps.alert(
                        title="Quit this session?",
                        message=f"Send Ctrl+C to {project} (pid {pid})?\n"
                        f"You can resume later with: claude -r {sid[:8]}...",
                        ok="Quit Session",
                        cancel="Keep Running",
                    )
                    if quit_response:
                        try:
                            os.kill(pid, signal.SIGINT)
                            log.info("session quit: pid=%d project=%s", pid, project)
                        except OSError:
                            log.warning("failed to quit session pid=%d", pid)
            finally:
                self._modal_active = False
                self._last_menu_key = ""
                self.update_display()

        return handler

    def _make_resume_handler(self, session_id: str, _cwd: str = ""):  # noqa: ANN202, ARG002
        def handler(_: rumps.MenuItem) -> None:
            # Validate session ID is a UUID to prevent command injection via clipboard
            if not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", session_id):
                log.warning("invalid session ID: %s", session_id[:20])
                return
            cmd = f"claude -r {session_id}"
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(cmd, NSStringPboardType)
            rumps.notification(
                title="Resume command copied",
                subtitle="",
                message=f"Paste in terminal: {cmd[:40]}...",
                sound=False,
            )

        return handler

    def _make_remove_saved_handler(self, session_id: str):  # noqa: ANN202
        def handler(_: rumps.MenuItem) -> None:
            remove_bookmark(session_id)
            self._last_menu_key = ""
            self.update_display()

        return handler

    def _open_accessibility(self, _: rumps.MenuItem) -> None:
        """Open System Settings to the Accessibility pane."""
        subprocess.run(  # noqa: S603, S607
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            check=False,
        )
        self._check_accessibility()

    def _open_preferences(self, _: rumps.MenuItem) -> None:
        show_preferences()

    def _quit(self, _: rumps.MenuItem) -> None:
        rumps.quit_application()


def main() -> None:
    """Entry point for the claudewatch command."""
    # No console output — all logging goes to the audit file only
    logger = logging.getLogger("claudewatch")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # prevent root logger from printing to stderr

    audit_dir = os.path.expanduser("~/.claude")
    if os.path.isdir(audit_dir):
        audit_path = os.path.join(audit_dir, "claudewatch.log")
        if not os.path.exists(audit_path):
            os.open(audit_path, os.O_CREAT | os.O_WRONLY, 0o600)
        file_handler = logging.handlers.RotatingFileHandler(
            audit_path,
            maxBytes=1_000_000,
            backupCount=3,
        )
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        ))
        logger.addHandler(file_handler)

    # Set up native notifications (Info.plist + delegate)
    ensure_info_plist()
    install_notification_delegate()

    ClaudeWatchApp().run()


@rumps.notifications
def _on_notification_click(notification: object) -> None:
    """Handle notification click — focus the relevant session window."""
    data = getattr(notification, "data", None)
    if data and isinstance(data, dict) and "pid" in data:
        try:
            handle_notification_click(data)
        except Exception:
            log.exception("notification click handler failed")
