import ctypes
import logging
import logging.handlers
import os
import re
import signal
import subprocess
import threading
import time
import webbrowser
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import objc
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBezierPath,
    NSColor,
    NSFont,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSMutableAttributedString,
    NSObject,
    NSStatusBar,
    NSString,
    NSTextField,
    NSWorkspace,
)
from Foundation import NSMakeRect, NSMakeSize, NSRange, NSTimer
from PyObjCTools import AppHelper

from claudewatch.backend.helpers import escape_applescript, run_applescript
from claudewatch.backend.models import (
    HOST_APP_PATH,
    ClaudeSession,
    HostApp,
    SessionStatus,
)
from claudewatch.backend.repositories.bookmarks import get_pinned_cwds, get_pins, pin_session, unpin_session
from claudewatch.backend.repositories.config import get_setting
from claudewatch.backend.repositories.history import get_history, record_session, remove_history_entry
from claudewatch.backend.services.detection import detect_sessions
from claudewatch.backend.services.notifications import TERMINAL_NOTIFIER, NotificationManager
from claudewatch.backend.services.onboarding import (
    get_session_count,
    increment_session_count,
    is_tip_shown,
    replay_all_tips,
    show_tip,
)
from claudewatch.backend.services.summarize import (
    cache_summary,
    generate_and_cache_summary,
    get_cached_summary,
    is_generating,
    track_session,
)
from claudewatch.backend.services.updates import check_for_update, get_cached_update
from claudewatch.backend.services.usage import (
    MODEL_DISPLAY_NAMES,
    format_tokens_breakdown,
    get_session_model,
    get_session_tokens,
)
from claudewatch.ui.activity import show_activity
from claudewatch.ui.focus import focus_session
from claudewatch.ui.preferences import show_preferences

# Type alias for menu item click handlers
_MenuCallback = Callable[[NSMenuItem], None]

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


def _clean_exit_session(tty: str, pid: int, project: str, window_id: int | None = None) -> bool:
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


def _notify_paused(project: str) -> None:
    """Send a 'session paused' notification via terminal-notifier."""
    if not TERMINAL_NOTIFIER:
        return
    subprocess.Popen(  # noqa: S603
        [TERMINAL_NOTIFIER, "-title", "Session paused", "-subtitle", project,
         "-message", "Resume from the Pinned section"],
    )


def _noop(_: NSMenuItem) -> None:
    """No-op callback — keeps menu items enabled (not greyed out)."""


def _make_menu_item(title: str, callback: _MenuCallback | None, delegate: "_AppDelegate") -> NSMenuItem:
    """Create an NSMenuItem, wiring its callback through the delegate."""
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
    if callback is not None:
        tag = delegate._next_tag
        delegate._next_tag += 1
        item.setTag_(tag)
        item.setTarget_(delegate)
        item.setAction_("menuItemClicked:")
        delegate._callbacks[tag] = callback
    return item


def _add_summary_lines(submenu: NSMenu, text: str, delegate: "_AppDelegate") -> None:
    """Split a summary into wrapped menu items — non-interactive, readable text."""
    _wrap = 55
    words = text.split()
    line = ""
    for word in words:
        if line and len(line) + 1 + len(word) > _wrap:
            item = _make_menu_item(f"  {line}", None, delegate)
            _style_summary_item(item)
            submenu.addItem_(item)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        item = _make_menu_item(f"  {line}", None, delegate)
        _style_summary_item(item)
        submenu.addItem_(item)


def _style_summary_item(item: NSMenuItem) -> None:
    """Apply readable font styling to a summary menu item."""
    text = str(item.title())
    attr = NSMutableAttributedString.alloc().initWithString_(text)
    r = NSRange(0, len(text))
    attr.addAttribute_value_range_("NSFont", NSFont.systemFontOfSize_(12.0), r)
    attr.addAttribute_value_range_("NSColor", NSColor.labelColor(), r)
    item.setAttributedTitle_(attr)


_MAX_ERRORS = 10


class _AppDelegate(NSObject):
    """Handles NSMenuItem actions and poll timer ticks."""

    _callbacks: dict[int, Callable]
    _next_tag: int
    _app: "ClaudeWatchApp | None"

    def init(self):  # noqa: ANN202
        self = objc.super(_AppDelegate, self).init()  # noqa: PLW0642
        if self is not None:
            self._callbacks = {}
            self._next_tag = 1
            self._app = None
        return self

    def menuItemClicked_(self, sender: NSMenuItem) -> None:  # noqa: N802
        cb = self._callbacks.get(sender.tag())
        if cb:
            cb(sender)

    def pollTick_(self, timer: object) -> None:  # noqa: N802, ARG002
        if self._app:
            self._app.poll()


class ClaudeWatchApp:
    def __init__(self, delegate: _AppDelegate) -> None:
        self._delegate = delegate
        self._menu = NSMenu.alloc().init()
        self._menu.setAutoenablesItems_(False)
        self._status_item: object | None = None
        self.sessions: list[ClaudeSession] = []
        self._last_menu_key = "__uninitialized__"
        self._consecutive_errors = 0
        self.notifications = NotificationManager()
        self._future: Future | None = None  # type: ignore[type-arg]
        self._last_poll_time = 0.0
        self._modal_active = False
        self._prev_pids: set[int] = set()
        self._prev_status: dict[int, str] = {}
        self._prev_sessions: dict[int, ClaudeSession] = {}
        self._exiting_pids: dict[int, float] = {}  # PID → time of quit signal
        self._has_polled = False
        self._check_accessibility()
        # Run first detection synchronously so menu has data immediately
        try:
            self.sessions = detect_sessions()
            self._has_polled = True
        except Exception:
            log.exception("initial detection failed")
        self.update_display()
        # Kick off background update check
        threading.Thread(target=check_for_update, daemon=True).start()

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
                model = get_session_model(s.cwd)
                log.info(
                    "session.started project=%s host=%s model=%s pid=%d",
                    s.project,
                    s.host_app.value,
                    model or "unknown",
                    pid,
                )

        # Track cumulative session count for onboarding "hover" tip
        if new_pids and not is_tip_shown("hover"):
            increment_session_count(len(new_pids))

        # Ended sessions — record to history
        for pid in self._prev_pids - current_pids:
            log.info("session.ended pid=%d", pid)
            prev = self._prev_sessions.get(pid)
            if prev:
                record_session(
                    session_id=prev.session_id,
                    project=prev.project,
                    cwd=prev.cwd,
                    model=get_session_model(prev.cwd),
                    host_app=prev.host_app.value,
                )

        # No status transition logging — it's polling noise.
        # Meaningful events (notifications, pins, quits, resumes) are
        # logged where they happen.

        self._prev_pids = current_pids
        self._prev_status = current_status
        self._prev_sessions = session_map

    def _check_onboarding_tips(self) -> None:
        """Fire one-time onboarding tips based on current state."""
        # Welcome — first successful poll
        if not is_tip_shown("welcome"):
            show_tip("welcome")
            return  # one tip per cycle

        # Attention — first time a session needs attention
        if not is_tip_shown("attention") and any(s.status == SessionStatus.ATTENTION for s in self.sessions):
            show_tip("attention")
            return

        # Hover — after 5 cumulative unique sessions observed
        _hover_threshold = 5
        if not is_tip_shown("hover") and get_session_count() >= _hover_threshold:
            show_tip("hover")

    def _check_accessibility(self) -> None:
        """Show a warning if Accessibility permissions are not granted."""
        if not _is_accessibility_trusted():
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
                self.update_display()
                self.notifications.notify_if_needed(self.sessions)
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
                    self._menu.addItem_(_make_menu_item("Too many errors — restart app", None, self._delegate))
                    self._menu.addItem_(NSMenuItem.separatorItem())
                    self._menu.addItem_(_make_menu_item("Quit", self._quit, self._delegate))
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
        if self._status_item is not None:
            self._status_item.setImage_(status_icon)
            self._status_item.setTitle_("")

        key = self._menu_key()
        if key == self._last_menu_key:
            return
        self._last_menu_key = key

        self._menu.removeAllItems()
        self._delegate._callbacks.clear()
        self._delegate._next_tag = 1
        d = self._delegate

        # App title
        self._menu.addItem_(_make_menu_item("ClaudeWatch", None, d))
        self._menu.addItem_(NSMenuItem.separatorItem())

        # Update available?
        update_info = get_cached_update()
        if update_info:
            self._menu.addItem_(
                _make_menu_item(
                    f"Update available ({update_info['tag']})",
                    self._make_open_update_handler(),
                    d,
                )
            )
            self._menu.addItem_(NSMenuItem.separatorItem())

        # Show accessibility warning if needed
        if self._accessibility_warning:
            self._menu.addItem_(
                _make_menu_item("⚠️ Grant Accessibility in System Settings", self._open_accessibility, d)
            )
            self._menu.addItem_(NSMenuItem.separatorItem())

        pinned_cwds = get_pinned_cwds()
        active_cwds = {s.cwd for s in self.sessions}

        if not self.sessions:
            if self._has_polled:
                self._menu.addItem_(_make_menu_item("No running Claude sessions", None, d))
            else:
                self._menu.addItem_(_make_menu_item("Scanning for Claude sessions…", None, d))
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
                header = _make_menu_item("⚠ Needs Attention", None, d)
                header.setAttributedTitle_(
                    _make_header_title("⚠ Needs Attention", SessionStatus.ATTENTION, len(attention)),
                )
                self._menu.addItem_(header)
                for s in attention:
                    is_pinned = s.cwd in pinned_cwds
                    self._add_session_items(s, suffixes[s.pid], pinned=is_pinned)

            if attention and (working or idle):
                self._menu.addItem_(NSMenuItem.separatorItem())

            if working:
                header = _make_menu_item("✦ Working", None, d)
                header.setAttributedTitle_(
                    _make_header_title("✦ Working", SessionStatus.WORKING, len(working)),
                )
                self._menu.addItem_(header)
                for s in working:
                    is_pinned = s.cwd in pinned_cwds
                    self._add_session_items(s, suffixes[s.pid], pinned=is_pinned)

            if working and idle:
                self._menu.addItem_(NSMenuItem.separatorItem())

            if idle:
                header = _make_menu_item("⏸ Idle", None, d)
                header.setAttributedTitle_(
                    _make_header_title("⏸ Idle", SessionStatus.IDLE, len(idle)),
                )
                self._menu.addItem_(header)
                for s in idle:
                    is_pinned = s.cwd in pinned_cwds
                    self._add_session_items(s, suffixes[s.pid], pinned=is_pinned)

        # Pinned sessions that are NOT currently active
        pins = get_pins()
        inactive_pins = [p for p in pins if p.get("cwd", "") not in active_cwds]
        if inactive_pins:
            self._menu.addItem_(NSMenuItem.separatorItem())
            self._menu.addItem_(_make_menu_item(f"★ Pinned ({len(inactive_pins)})", None, d))
            for entry in inactive_pins:
                sid = entry.get("session_id", "")
                proj = entry.get("project", "unknown")
                note = entry.get("note", "")
                cwd = entry.get("cwd", "")
                _max_note = 25
                label = f"  {proj}"
                if note:
                    short_note = note[:_max_note] + "…" if len(note) > _max_note else note
                    label += f" — {short_note}"
                item = _make_menu_item(label, self._make_resume_handler(sid, cwd), d)
                # Summary submenu
                summary_menu = NSMenu.alloc().init()
                summary_item = _make_menu_item("Summary", None, d)
                cached = get_cached_summary(cwd)
                if cached:
                    _add_summary_lines(summary_menu, cached, d)
                elif note:
                    _add_summary_lines(summary_menu, note, d)
                else:
                    summary_menu.addItem_(_make_menu_item("No summary available", None, d))
                summary_item.setSubmenu_(summary_menu)
                sub = NSMenu.alloc().init()
                sub.addItem_(summary_item)
                sub.addItem_(NSMenuItem.separatorItem())
                sub.addItem_(_make_menu_item("Unpin", self._make_unpin_handler(cwd), d))
                item.setSubmenu_(sub)
                self._menu.addItem_(item)
                # Date + model
                detail_parts = []
                ts = entry.get("timestamp", "")
                if ts:
                    detail_parts.append(ts[:10])
                model = get_session_model(cwd)
                if model:
                    detail_parts.append(model)
                if detail_parts:
                    self._menu.addItem_(_make_menu_item(f"      {' · '.join(detail_parts)}", None, d))

        # Recent sessions (last 3 days, not active, not pinned)
        _recent_days = 3
        _recent_limit = 10
        cutoff = datetime.now(tz=UTC) - timedelta(days=_recent_days)
        history = get_history()  # newest-first
        recent_entries = []
        for entry in history:
            if len(recent_entries) >= _recent_limit:
                break
            cwd = entry.get("cwd", "")
            ended_at = entry.get("ended_at", "")
            if cwd in active_cwds or cwd in pinned_cwds:
                continue
            try:
                ended_dt = datetime.fromisoformat(ended_at)
                if ended_dt < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
            recent_entries.append(entry)

        if recent_entries:
            self._menu.addItem_(NSMenuItem.separatorItem())
            recent_menu_item = _make_menu_item(f"⏱ Recent ({len(recent_entries)})", None, d)
            recent_submenu = NSMenu.alloc().init()
            for entry in recent_entries:
                sid = entry.get("session_id", "")
                proj = entry.get("project", "unknown")
                cwd = entry.get("cwd", "")
                raw_model = entry.get("model", "")
                model = MODEL_DISPLAY_NAMES.get(raw_model, raw_model)
                ended_at = entry.get("ended_at", "")

                detail_parts = [p for p in [ended_at[:10] if ended_at else "", model] if p]
                label = proj
                if detail_parts:
                    label += f"  ({' · '.join(detail_parts)})"
                item = _make_menu_item(label, _noop, d)
                item_sub = NSMenu.alloc().init()
                # Summary submenu
                summary_text = get_cached_summary(cwd)
                if summary_text:
                    summary_item = _make_menu_item("Summary", None, d)
                    summary_sub = NSMenu.alloc().init()
                    _add_summary_lines(summary_sub, summary_text, d)
                    summary_item.setSubmenu_(summary_sub)
                    item_sub.addItem_(summary_item)
                # Usage submenu with token breakdown + Activity
                token_data = get_session_tokens(cwd)
                breakdown = format_tokens_breakdown(token_data)
                usage_item = _make_menu_item("Usage", None, d)
                usage_sub = NSMenu.alloc().init()
                if breakdown:
                    for uline in breakdown:
                        usage_sub.addItem_(_make_menu_item(f"  {uline}", None, d))
                    usage_sub.addItem_(NSMenuItem.separatorItem())
                usage_sub.addItem_(
                    _make_menu_item(
                        "View session activity log",
                        self._make_history_activity_handler(proj, cwd),
                        d,
                    )
                )
                usage_item.setSubmenu_(usage_sub)
                item_sub.addItem_(usage_item)
                item_sub.addItem_(NSMenuItem.separatorItem())
                if sid:
                    item_sub.addItem_(_make_menu_item("Resume", self._make_resume_handler(sid, cwd), d))
                item_sub.addItem_(_make_menu_item("Remove", self._make_remove_history_handler(cwd), d))
                item.setSubmenu_(item_sub)
                recent_submenu.addItem_(item)
                track_session(cwd)  # background thread will generate summary
            recent_menu_item.setSubmenu_(recent_submenu)
            self._menu.addItem_(recent_menu_item)

        self._menu.addItem_(NSMenuItem.separatorItem())
        self._menu.addItem_(_make_menu_item("Preferences...", self._open_preferences, d))

        help_item = _make_menu_item("Help", None, d)
        help_submenu = NSMenu.alloc().init()
        for tip in (
            "Click → focus window",
            "Hover → Activity · Pin · Quit",
            "★ = pinned (resume later)",
        ):
            help_submenu.addItem_(_make_menu_item(f"  {tip}", None, d))

        # Color legend with actual colored dots
        legend = _make_menu_item("  Status dots", None, d)
        legend_text = NSMutableAttributedString.alloc().initWithString_("")
        _legend_font = NSFont.menuFontOfSize_(13.0)
        for label, status in (
            ("  ● attention  ", SessionStatus.ATTENTION),
            ("● working  ", SessionStatus.WORKING),
            ("● idle", SessionStatus.IDLE),
        ):
            seg = NSMutableAttributedString.alloc().initWithString_(label)
            r = NSRange(0, len(label))
            seg.addAttribute_value_range_("NSFont", _legend_font, r)
            dot_end = label.index("●") + 1
            seg.addAttribute_value_range_(
                "NSColor",
                _STATUS_COLORS[status],
                NSRange(label.index("●"), 1),
            )
            seg.addAttribute_value_range_(
                "NSColor",
                NSColor.secondaryLabelColor(),
                NSRange(dot_end, len(label) - dot_end),
            )
            legend_text.appendAttributedString_(seg)
        legend.setAttributedTitle_(legend_text)
        help_submenu.addItem_(legend)
        help_submenu.addItem_(NSMenuItem.separatorItem())
        help_submenu.addItem_(_make_menu_item("Show Tips", self._replay_tips, d))
        help_submenu.addItem_(_make_menu_item("GitHub", self._open_github, d))
        help_item.setSubmenu_(help_submenu)
        self._menu.addItem_(help_item)

        self._menu.addItem_(_make_menu_item("Quit", self._quit, d))

    def _add_session_items(self, s: ClaudeSession, suffix: str = "", *, pinned: bool = False) -> None:  # noqa: PLR0912, PLR0915
        """Add a session entry + detail line to the menu."""
        d = self._delegate
        pin_mark = " ★" if pinned else ""
        label = s.menu_label + suffix + pin_mark
        item = _make_menu_item(label, self._make_click_handler(s), d)
        icon = _get_app_icon(s.host_app)
        if icon:
            item.setImage_(icon)
        # Build submenu for this session
        sub = NSMenu.alloc().init()
        # Summary submenu — auto-generates in background
        summary_item = _make_menu_item("Summary", None, d)
        summary_sub = NSMenu.alloc().init()
        cached = get_cached_summary(s.cwd)
        if cached:
            _add_summary_lines(summary_sub, cached, d)
        elif is_generating(s.cwd):
            summary_sub.addItem_(_make_menu_item("Generating…", None, d))
        else:
            summary_sub.addItem_(_make_menu_item("Pending…", None, d))
        summary_item.setSubmenu_(summary_sub)
        sub.addItem_(summary_item)
        # Usage submenu with token breakdown + Activity link
        token_data = get_session_tokens(s.cwd)
        breakdown = format_tokens_breakdown(token_data)
        usage_item = _make_menu_item("Usage", None, d)
        usage_sub = NSMenu.alloc().init()
        if breakdown:
            for line in breakdown:
                usage_sub.addItem_(_make_menu_item(f"  {line}", None, d))
            usage_sub.addItem_(NSMenuItem.separatorItem())
        usage_sub.addItem_(_make_menu_item("View session activity log", self._make_activity_handler(s), d))
        usage_item.setSubmenu_(usage_sub)
        sub.addItem_(usage_item)
        sub.addItem_(NSMenuItem.separatorItem())
        # Track for background refresh (auto-generates summaries)
        track_session(s.cwd)
        if pinned:
            sub.addItem_(_make_menu_item("Unpin", self._make_unpin_handler(s.cwd), d))
            sub.addItem_(_make_menu_item("Quit session", self._make_quit_handler(s), d))
        else:
            if s.session_id:
                sub.addItem_(_make_menu_item("Pin session...", self._make_pin_handler(s), d))
            sub.addItem_(_make_menu_item("Quit session", self._make_quit_handler(s), d))
        item.setSubmenu_(sub)
        self._menu.addItem_(item)
        # Detail line: model + summary (or status as fallback)
        model = get_session_model(s.cwd)
        cached = get_cached_summary(s.cwd)
        _max_oneliner = 40
        if cached:
            oneliner = cached.replace("\n", " ").strip()
            if len(oneliner) > _max_oneliner:
                oneliner = oneliner[: _max_oneliner - 1] + "…"
        else:
            oneliner = s.detail_line
        detail_parts = [p for p in [model, oneliner] if p]
        if detail_parts:
            self._menu.addItem_(_make_menu_item(f"      {' · '.join(detail_parts)}", None, d))

    def _make_activity_handler(self, session: ClaudeSession) -> _MenuCallback:
        project = session.project
        cwd = session.cwd

        def handler(_: NSMenuItem) -> None:
            show_activity(project, cwd, session_active=True)

        return handler

    def _make_click_handler(self, session: ClaudeSession) -> _MenuCallback:
        pid = session.pid

        def handler(_: NSMenuItem) -> None:
            try:
                current = next((s for s in self.sessions if s.pid == pid), session)
                focus_session(current)
            except Exception:
                log.exception("focus error")

        return handler

    def _make_pin_handler(self, session: ClaudeSession) -> _MenuCallback:  # noqa: PLR0915
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
                alert.setMessageText_("Pin Session")
                alert.setInformativeText_(f"Add a note for {project}:")
                alert.addButtonWithTitle_("Pin")
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
                    summary = generate_and_cache_summary(cwd)
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
                    pin_session(sid, project, cwd, note)
                    show_tip("pin")
                    if note:
                        cache_summary(cwd, note)

                    quit_alert = NSAlert.alloc().init()
                    quit_alert.setMessageText_("Quit this session?")
                    quit_alert.setInformativeText_(f"Cleanly exit {project}?\nResume later from the Pinned section.")
                    quit_alert.addButtonWithTitle_("Quit Session")
                    quit_alert.addButtonWithTitle_("Keep Running")
                    if quit_alert.runModal() == NSAlertFirstButtonReturn:
                        _clean_exit_session(tty, pid, project, wid)
                        self._exiting_pids[pid] = time.time()
            finally:
                self._modal_active = False
                self._last_menu_key = ""
                self.update_display()

        return handler

    def _make_quit_handler(self, session: ClaudeSession) -> _MenuCallback:
        pid = session.pid
        project = session.project
        cwd = session.cwd
        tty = session.tty
        wid = session.window_id
        pinned = cwd in get_pinned_cwds()

        def handler(_: NSMenuItem) -> None:
            exited = False
            if pinned:
                _clean_exit_session(tty, pid, project, wid)
                self._exiting_pids[pid] = time.time()
                exited = True
                _notify_paused(project)
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
                        _clean_exit_session(tty, pid, project, wid)
                        self._exiting_pids[pid] = time.time()
                        exited = True
                finally:
                    self._modal_active = False
            if exited:
                threading.Thread(target=generate_and_cache_summary, args=(cwd,), daemon=True).start()
            self._last_menu_key = ""
            self.update_display()

        return handler

    def _make_unpin_handler(self, cwd: str) -> _MenuCallback:
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
                    unpin_session(cwd)
            finally:
                self._modal_active = False
                self._last_menu_key = ""
                self.update_display()

        return handler

    def _make_resume_handler(self, session_id: str, cwd: str = "") -> _MenuCallback:
        def handler(_: NSMenuItem) -> None:
            # Validate session ID is a UUID to prevent command injection
            if not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", session_id):
                log.warning("invalid session ID: %s", session_id[:20])
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

    def _make_history_activity_handler(self, project: str, cwd: str) -> _MenuCallback:
        def handler(_: NSMenuItem) -> None:
            show_activity(project, cwd)

        return handler

    def _make_remove_history_handler(self, cwd: str) -> _MenuCallback:
        def handler(_: NSMenuItem) -> None:
            remove_history_entry(cwd)
            self._last_menu_key = ""
            self.update_display()

        return handler

    def _make_open_update_handler(self) -> _MenuCallback:
        def handler(_: NSMenuItem) -> None:
            webbrowser.open("https://github.com/wingatethomas/claudewatch/releases/latest")

        return handler

    def _open_accessibility(self, _: NSMenuItem) -> None:
        """Open System Settings to the Accessibility pane."""
        subprocess.run(  # noqa: S603, S607
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            check=False,
        )
        self._check_accessibility()

    def _open_preferences(self, _: NSMenuItem) -> None:
        show_preferences()

    def _replay_tips(self, _: NSMenuItem) -> None:
        threading.Thread(target=replay_all_tips, daemon=True).start()

    def _open_github(self, _: NSMenuItem) -> None:
        webbrowser.open("https://github.com/wingatethomas/claudewatch")

    def _quit(self, _: NSMenuItem) -> None:
        AppHelper.stopEventLoop()


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
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        logger.addHandler(file_handler)

    signal.signal(signal.SIGINT, lambda *_: AppHelper.stopEventLoop())

    delegate = _AppDelegate.alloc().init()
    app = ClaudeWatchApp(delegate)
    delegate._app = app
    app.run()
