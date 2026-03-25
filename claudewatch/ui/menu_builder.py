"""Menu building — constructs the full NSMenu from session state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from AppKit import (
    NSColor,
    NSFont,
    NSMenu,
    NSMenuItem,
    NSMutableAttributedString,
)
from Foundation import NSRange

from claudewatch.backend.core.models import ClaudeSession, SessionStatus
from claudewatch.backend.usage.service import MODEL_DISPLAY_NAMES, format_tokens_breakdown
from claudewatch.ui.icons import (
    STATUS_COLORS,
    get_app_icon,
    make_header_title,
    render_status_icon,
    sf_icon,
)
from claudewatch.ui.menu_helpers import (
    AppDelegate,
    add_summary_lines,
    disabled_item,
    make_menu_item,
    noop,
)

if TYPE_CHECKING:
    from claudewatch.ui.menubar import ClaudeWatchApp


class MenuBuilder:
    """Builds the full menu from session state."""

    def __init__(self, app: ClaudeWatchApp, menu: NSMenu, delegate: AppDelegate) -> None:
        self._app = app
        self._menu = menu
        self._delegate = delegate

    def build(self, sessions: list[ClaudeSession]) -> None:  # noqa: PLR0912, PLR0915
        attention = [s for s in sessions if s.status == SessionStatus.ATTENTION]
        working = [s for s in sessions if s.status == SessionStatus.WORKING]
        idle = [s for s in sessions if s.status == SessionStatus.IDLE]

        # Menu bar icon — ✦ with colored dots for each state
        status_icon = render_status_icon(attention, working, idle)
        if self._app._status_item is not None:
            self._app._status_item.setImage_(status_icon)
            self._app._status_item.setTitle_("")

        key = self._app._menu_key()
        if key == self._app._last_menu_key:
            return
        self._app._last_menu_key = key

        self._menu.removeAllItems()
        self._delegate._callbacks.clear()
        self._delegate._next_tag = 1
        d = self._delegate

        # App title
        self._menu.addItem_(disabled_item("ClaudeWatch"))
        self._menu.addItem_(NSMenuItem.separatorItem())

        # Update available?
        update_info = self._app._update_service.get_cached()
        if update_info:
            self._menu.addItem_(
                make_menu_item(
                    f"Update to {update_info.tag}",
                    self._app._make_open_update_handler(),
                    d,
                )
            )
            self._menu.addItem_(NSMenuItem.separatorItem())

        # Show accessibility warning if needed
        if self._app._accessibility_warning:
            self._menu.addItem_(
                make_menu_item("⚠️ Grant Accessibility in System Settings", self._app._open_accessibility, d)
            )
            self._menu.addItem_(NSMenuItem.separatorItem())

        pinned_cwds = self._app._bookmark_service.get_pinned_cwds()
        active_cwds = {s.cwd for s in sessions}

        if not sessions:
            if self._app._has_polled:
                self._menu.addItem_(disabled_item("No running Claude sessions"))
            else:
                self._menu.addItem_(disabled_item("Scanning for Claude sessions…"))
        else:
            # Build suffix map to disambiguate duplicate labels
            seen_labels: dict[str, int] = {}
            suffixes: dict[int, str] = {}
            for s in sessions:
                label = s.menu_label
                seen_labels[label] = seen_labels.get(label, 0) + 1
            label_counters: dict[str, int] = {}
            for s in sessions:
                label = s.menu_label
                if seen_labels[label] > 1:
                    label_counters[label] = label_counters.get(label, 0) + 1
                    suffixes[s.pid] = f" #{label_counters[label]}"
                else:
                    suffixes[s.pid] = ""

            if attention:
                header = disabled_item("⚠ Needs Attention")
                header.setAttributedTitle_(
                    make_header_title("⚠ Needs Attention", SessionStatus.ATTENTION, len(attention)),
                )
                self._menu.addItem_(header)
                for s in attention:
                    is_pinned = s.cwd in pinned_cwds
                    self._add_session_items(s, suffixes[s.pid], pinned=is_pinned)

            if attention and (working or idle):
                self._menu.addItem_(NSMenuItem.separatorItem())

            if working:
                header = disabled_item("✦ Working")
                header.setAttributedTitle_(
                    make_header_title("✦ Working", SessionStatus.WORKING, len(working)),
                )
                self._menu.addItem_(header)
                for s in working:
                    is_pinned = s.cwd in pinned_cwds
                    self._add_session_items(s, suffixes[s.pid], pinned=is_pinned)

            if working and idle:
                self._menu.addItem_(NSMenuItem.separatorItem())

            if idle:
                header = disabled_item("⏸ Idle")
                header.setAttributedTitle_(
                    make_header_title("⏸ Idle", SessionStatus.IDLE, len(idle)),
                )
                self._menu.addItem_(header)
                for s in idle:
                    is_pinned = s.cwd in pinned_cwds
                    self._add_session_items(s, suffixes[s.pid], pinned=is_pinned)

        # Pinned sessions that are NOT currently active
        pins = self._app._bookmark_service.get_pins()
        inactive_pins = [p for p in pins if p.cwd not in active_cwds]
        if inactive_pins:
            self._menu.addItem_(NSMenuItem.separatorItem())
            self._menu.addItem_(disabled_item(f"★ Pinned ({len(inactive_pins)})"))
            for pin in inactive_pins:
                _max_note = 25
                label = f"  {pin.project}"
                if pin.note:
                    short_note = pin.note[:_max_note] + "…" if len(pin.note) > _max_note else pin.note
                    label += f" — {short_note}"
                item = make_menu_item(label, self._app._make_resume_handler(pin.session_id, pin.cwd), d)
                # Summary submenu
                summary_menu = NSMenu.alloc().init()
                summary_item = make_menu_item("Summary", None, d)
                cached = self._app._summary_service.get_cached(pin.cwd)
                if cached:
                    add_summary_lines(summary_menu, cached, d)
                elif pin.note:
                    add_summary_lines(summary_menu, pin.note, d)
                else:
                    summary_menu.addItem_(make_menu_item("No summary available", None, d))
                summary_item.setSubmenu_(summary_menu)
                sub = NSMenu.alloc().init()
                sub.addItem_(summary_item)
                sub.addItem_(NSMenuItem.separatorItem())
                sub.addItem_(make_menu_item("Unpin", self._app._make_unpin_handler(pin.cwd), d))
                item.setSubmenu_(sub)
                self._menu.addItem_(item)
                # Date + model
                detail_parts = []
                if pin.timestamp:
                    detail_parts.append(pin.timestamp[:10])
                model = self._app._usage_service.get_model(pin.cwd)
                if model:
                    detail_parts.append(model)
                if detail_parts:
                    self._menu.addItem_(disabled_item(f"      {' · '.join(detail_parts)}"))

        # Recent sessions (last 3 days, not active, not pinned)
        _recent_days = 3
        _recent_limit = 10
        cutoff = datetime.now(tz=UTC) - timedelta(days=_recent_days)
        history = self._app._history_service.get_all()  # newest-first
        recent_entries = []
        for entry in history:
            if len(recent_entries) >= _recent_limit:
                break
            if entry.cwd in active_cwds or entry.cwd in pinned_cwds:
                continue
            try:
                ended_dt = datetime.fromisoformat(entry.ended_at)
                if ended_dt < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
            recent_entries.append(entry)

        if recent_entries:
            self._menu.addItem_(NSMenuItem.separatorItem())
            recent_menu_item = make_menu_item(f"Recent ({len(recent_entries)})", None, d)
            recent_menu_item.setImage_(sf_icon("clock.arrow.circlepath"))
            recent_submenu = NSMenu.alloc().init()
            for entry in recent_entries:
                model = MODEL_DISPLAY_NAMES.get(entry.model, entry.model)

                detail_parts = [p for p in [entry.ended_at[:10] if entry.ended_at else "", model] if p]
                label = entry.project
                if detail_parts:
                    label += f"  ({' · '.join(detail_parts)})"
                item = make_menu_item(label, noop, d)
                item_sub = NSMenu.alloc().init()
                # Summary submenu
                summary_text = self._app._summary_service.get_cached(entry.cwd)
                if summary_text:
                    summary_item = make_menu_item("Summary", None, d)
                    summary_sub = NSMenu.alloc().init()
                    add_summary_lines(summary_sub, summary_text, d)
                    summary_item.setSubmenu_(summary_sub)
                    item_sub.addItem_(summary_item)
                # Usage submenu with token breakdown + Activity
                token_data = self._app._usage_service.get_tokens(entry.cwd)
                breakdown = format_tokens_breakdown(token_data)
                usage_item = make_menu_item("Usage", None, d)
                usage_sub = NSMenu.alloc().init()
                if breakdown:
                    for uline in breakdown:
                        usage_sub.addItem_(make_menu_item(f"  {uline}", None, d))
                    usage_sub.addItem_(NSMenuItem.separatorItem())
                usage_sub.addItem_(
                    make_menu_item(
                        "View session activity log",
                        self._app._make_history_activity_handler(entry.project, entry.cwd),
                        d,
                    )
                )
                usage_item.setSubmenu_(usage_sub)
                item_sub.addItem_(usage_item)
                item_sub.addItem_(NSMenuItem.separatorItem())
                if entry.session_id:
                    item_sub.addItem_(make_menu_item("Resume", self._app._make_resume_handler(entry.session_id, entry.cwd), d))
                item_sub.addItem_(make_menu_item("Remove", self._app._make_remove_history_handler(entry.cwd), d))
                item.setSubmenu_(item_sub)
                recent_submenu.addItem_(item)
                self._app._summary_service.track_session(entry.cwd)  # background thread will generate summary
            recent_menu_item.setSubmenu_(recent_submenu)
            self._menu.addItem_(recent_menu_item)

        self._menu.addItem_(NSMenuItem.separatorItem())
        prefs_item = make_menu_item("Preferences...", self._app._open_preferences, d)
        prefs_item.setImage_(sf_icon("gearshape"))
        self._menu.addItem_(prefs_item)

        help_item = make_menu_item("Help", None, d)
        help_item.setImage_(sf_icon("questionmark.circle"))
        help_submenu = NSMenu.alloc().init()
        for tip in (
            "Click → focus window",
            "Hover → Activity · Pin · Quit",
            "★ = pinned (resume later)",
        ):
            help_submenu.addItem_(make_menu_item(f"  {tip}", None, d))

        # Color legend with actual colored dots
        legend = make_menu_item("  Status dots", None, d)
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
                STATUS_COLORS[status],
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
        help_submenu.addItem_(make_menu_item("Show Tips", self._app._replay_tips, d))
        help_submenu.addItem_(make_menu_item("GitHub", self._app._open_github, d))
        help_item.setSubmenu_(help_submenu)
        self._menu.addItem_(help_item)

        restart_item = make_menu_item("Restart", self._app._restart, d)
        restart_item.setImage_(sf_icon("arrow.clockwise"))
        self._menu.addItem_(restart_item)
        quit_item = make_menu_item("Quit", self._app._quit, d)
        quit_item.setImage_(sf_icon("xmark.circle"))
        self._menu.addItem_(quit_item)

    def _add_session_items(self, s: ClaudeSession, suffix: str = "", *, pinned: bool = False) -> None:  # noqa: PLR0912, PLR0915
        """Add a session entry + detail line to the menu."""
        d = self._delegate
        pin_mark = " ★" if pinned else ""
        label = s.menu_label + suffix + pin_mark
        item = make_menu_item(label, self._app._make_click_handler(s), d)
        icon = get_app_icon(s.host_app)
        if icon:
            item.setImage_(icon)
        # Build submenu for this session
        sub = NSMenu.alloc().init()
        # Summary submenu — auto-generates in background
        summary_item = make_menu_item("Summary", None, d)
        summary_sub = NSMenu.alloc().init()
        cached = self._app._summary_service.get_cached(s.cwd)
        if cached:
            add_summary_lines(summary_sub, cached, d)
        elif self._app._summary_service.is_generating(s.cwd):
            summary_sub.addItem_(make_menu_item("Generating…", None, d))
        else:
            summary_sub.addItem_(make_menu_item("Pending…", None, d))
        summary_item.setSubmenu_(summary_sub)
        sub.addItem_(summary_item)
        # Usage submenu with token breakdown + Activity link
        token_data = self._app._usage_service.get_tokens(s.cwd)
        breakdown = format_tokens_breakdown(token_data)
        usage_item = make_menu_item("Usage", None, d)
        usage_sub = NSMenu.alloc().init()
        if breakdown:
            for line in breakdown:
                usage_sub.addItem_(make_menu_item(f"  {line}", None, d))
            usage_sub.addItem_(NSMenuItem.separatorItem())
        usage_sub.addItem_(make_menu_item("View session activity log", self._app._make_activity_handler(s), d))
        usage_item.setSubmenu_(usage_sub)
        sub.addItem_(usage_item)
        sub.addItem_(NSMenuItem.separatorItem())
        # Track for background refresh (auto-generates summaries)
        self._app._summary_service.track_session(s.cwd)
        if pinned:
            sub.addItem_(make_menu_item("Unpin", self._app._make_unpin_handler(s.cwd), d))
            sub.addItem_(make_menu_item("Quit session", self._app._make_quit_handler(s), d))
        else:
            if s.session_id:
                sub.addItem_(make_menu_item("Pin session...", self._app._make_pin_handler(s), d))
            sub.addItem_(make_menu_item("Quit session", self._app._make_quit_handler(s), d))
        item.setSubmenu_(sub)
        self._menu.addItem_(item)
        # Detail line: model + summary (or status as fallback)
        model = self._app._usage_service.get_model(s.cwd)
        cached = self._app._summary_service.get_cached(s.cwd)
        _max_oneliner = 40
        if cached:
            oneliner = cached.replace("\n", " ").strip()
            if len(oneliner) > _max_oneliner:
                oneliner = oneliner[: _max_oneliner - 1] + "…"
        else:
            oneliner = s.detail_line
        detail_parts = [p for p in [model, oneliner] if p]
        if detail_parts:
            self._menu.addItem_(disabled_item(f"      {' · '.join(detail_parts)}"))
