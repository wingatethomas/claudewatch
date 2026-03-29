"""Menu building — constructs the full NSMenu from session state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from AppKit import (
    NSFont,
    NSMenu,
    NSMenuItem,
    NSMutableAttributedString,
)
from Foundation import NSRange

from claudewatch.backend.core import features
from claudewatch.backend.core.models import ClaudeSession, SessionStatus
from claudewatch.backend.core.paths import is_homebrew_install
from claudewatch.backend.usage.service import MODEL_DISPLAY_NAMES, format_tokens_breakdown
from claudewatch.ui.icons import (
    get_app_icon,
    get_status_colors,
    make_header_title,
    render_status_icon,
    sf_icon,
)
from claudewatch.ui.menu.core import (
    AppDelegate,
    disabled_item,
    make_menu_item,
    noop,
)
from claudewatch.ui.menu.session_submenu import AgentInfo, SessionActions, build_session_submenu
from claudewatch.ui.theme import theme

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
            if is_homebrew_install():
                self._menu.addItem_(
                    make_menu_item(
                        f"Update to {update_info.tag} (brew)",
                        self._app._copy_brew_update,
                        d,
                    )
                )
            else:
                self._menu.addItem_(
                    make_menu_item(
                        f"Update to {update_info.tag}",
                        self._app._make_open_update_handler(),
                        d,
                    )
                )
            self._menu.addItem_(NSMenuItem.separatorItem())

        # Guide nudge — submenu with view guide + dismiss
        if not self._app._onboarding_service.is_tip_shown("guide_nudge"):
            guide_item = make_menu_item("Getting Started", None, d)
            guide_sub = NSMenu.alloc().init()
            guide_sub.addItem_(make_menu_item("View Guide", self._app._open_guide, d))
            guide_sub.addItem_(make_menu_item("Don't show again", self._app._dismiss_guide, d))
            guide_item.setSubmenu_(guide_sub)
            self._menu.addItem_(guide_item)
            self._menu.addItem_(NSMenuItem.separatorItem())

        # Show accessibility warning if needed
        if self._app._accessibility_warning:
            self._menu.addItem_(
                make_menu_item("⚠️ Grant Accessibility in System Settings", self._app._open_accessibility, d)
            )
            self._menu.addItem_(NSMenuItem.separatorItem())

        pinned_cwds = self._app._bookmark_service.get_bookmarked_cwds()
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

        # Bookmarked sessions that are NOT currently active (respects feature toggle)
        pins = self._app._bookmark_service.get_all() if features.is_enabled("bookmarks") else []
        inactive_pins = [p for p in pins if p.cwd not in active_cwds]
        if inactive_pins:
            self._menu.addItem_(NSMenuItem.separatorItem())
            bm_menu_item = make_menu_item(f"Bookmarks ({len(inactive_pins)})", None, d)
            bm_menu_item.setImage_(sf_icon("bookmark.fill"))
            bm_submenu = NSMenu.alloc().init()
            for pin in inactive_pins:
                _max_note = 25
                label = pin.project
                if pin.note:
                    short_note = pin.note[:_max_note] + "…" if len(pin.note) > _max_note else pin.note
                    label += f" — {short_note}"
                item = make_menu_item(label, self._app._make_resume_handler(pin.session_id, pin.cwd), d)
                token_data = self._app._usage_service.get_tokens(pin.cwd)
                actions = SessionActions(
                    activity=self._app._make_history_activity_handler(pin.project, pin.cwd),
                    resume=self._app._make_resume_handler(pin.session_id, pin.cwd),
                    unbookmark=self._app._make_unbookmark_handler(pin.cwd),
                    track_summary=lambda cwd=pin.cwd: self._app._summary_service.track_session(cwd),
                    usage_lines=format_tokens_breakdown(token_data),
                )
                sub = build_session_submenu(
                    delegate=d,
                    summary=self._app._summary_service.get_cached_summary(pin.cwd),
                    actions=actions,
                )
                item.setSubmenu_(sub)
                bm_submenu.addItem_(item)
            bm_menu_item.setSubmenu_(bm_submenu)
            self._menu.addItem_(bm_menu_item)

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
                click_action = self._app._make_resume_handler(entry.session_id, entry.cwd) if entry.session_id else noop
                item = make_menu_item(label, click_action, d)
                token_data = self._app._usage_service.get_tokens(entry.cwd)
                actions = SessionActions(
                    activity=self._app._make_history_activity_handler(entry.project, entry.cwd),
                    resume=self._app._make_resume_handler(entry.session_id, entry.cwd) if entry.session_id else None,
                    remove=self._app._make_remove_history_handler(entry.cwd),
                    track_summary=lambda cwd=entry.cwd: self._app._summary_service.track_session(cwd),
                    usage_lines=format_tokens_breakdown(token_data),
                )
                item_sub = build_session_submenu(
                    delegate=d,
                    summary=self._app._summary_service.get_cached_summary(entry.cwd),
                    actions=actions,
                )
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

        # Color legend with colored dots
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
                get_status_colors()[status],
                NSRange(label.index("●"), 1),
            )
            seg.addAttribute_value_range_(
                "NSColor",
                theme.secondary,
                NSRange(dot_end, len(label) - dot_end),
            )
            legend_text.appendAttributedString_(seg)
        legend.setAttributedTitle_(legend_text)
        help_submenu.addItem_(legend)
        help_submenu.addItem_(NSMenuItem.separatorItem())
        help_submenu.addItem_(make_menu_item("Guide", self._app._open_guide, d))
        help_submenu.addItem_(make_menu_item("GitHub", self._app._open_github, d))
        help_item.setSubmenu_(help_submenu)
        self._menu.addItem_(help_item)

        quit_item = make_menu_item("Quit", self._app._quit, d)
        quit_item.setImage_(sf_icon("xmark.circle"))
        self._menu.addItem_(quit_item)

    def _add_session_items(self, s: ClaudeSession, suffix: str = "", *, pinned: bool = False) -> None:  # noqa: PLR0912, PLR0915
        """Add a session entry + detail line to the menu."""
        d = self._delegate
        bm_mark = " ▸" if pinned else ""
        label = s.menu_label + suffix + bm_mark
        item = make_menu_item(label, self._app._make_click_handler(s), d)
        icon = get_app_icon(s.host_app)
        if icon:
            item.setImage_(icon)
        # Build submenu using shared session_submenu builder
        is_active = s.status in (SessionStatus.ATTENTION, SessionStatus.WORKING)
        token_data = self._app._usage_service.get_tokens(s.cwd)
        # Fetch agent details if session has agents
        agent_infos: list[AgentInfo] = []
        if s.agent_count > 0:
            scanned = self._app._graph_service.get_agent_details(s.cwd, s.session_id)
            agent_infos = [
                AgentInfo(
                    agent_type=a.agent_type,
                    description=a.description,
                    entry_count=a.entry_count,
                    status=a.status.value,
                )
                for a in scanned
            ]

        actions = SessionActions(
            activity=self._app._make_activity_handler(s),
            bookmark=self._app._make_bookmark_handler(s) if not pinned and s.session_id else None,
            unbookmark=self._app._make_unbookmark_handler(s.cwd) if pinned else None,
            quit=self._app._make_quit_handler(s),
            track_summary=lambda cwd=s.cwd, urgent=is_active: self._app._summary_service.track_session(
                cwd, urgent=urgent
            ),
            usage_lines=format_tokens_breakdown(token_data),
            agents=agent_infos,
        )
        sub = build_session_submenu(
            delegate=d,
            summary=self._app._summary_service.get_cached_summary(s.cwd),
            generating=self._app._summary_service.is_generating(s.cwd),
            actions=actions,
        )
        self._app._summary_service.track_session(s.cwd, urgent=is_active)
        item.setSubmenu_(sub)
        self._menu.addItem_(item)
        # Detail line: model + summary (or status as fallback)
        model = self._app._usage_service.get_model(s.cwd)
        cached = self._app._summary_service.get_cached(s.cwd)
        generating = self._app._summary_service.is_generating(s.cwd)
        _max_detail_total = 55
        if cached:
            oneliner = cached.replace("\n", " ").strip()
        elif generating:
            oneliner = "Generating summary…"
        else:
            oneliner = s.detail_line
        agent_tag = f"{s.agent_count} agents" if s.agent_count > 1 else "1 agent" if s.agent_count == 1 else ""
        detail_parts = [p for p in [model, agent_tag, oneliner] if p]
        if detail_parts:
            detail_text = " · ".join(detail_parts)
            if len(detail_text) > _max_detail_total:
                # Truncate at word boundary
                truncated = detail_text[: _max_detail_total - 1]
                last_space = truncated.rfind(" ")
                if last_space > _max_detail_total // 2:
                    truncated = truncated[:last_space]
                detail_text = truncated + "…"
            self._menu.addItem_(disabled_item(f"      {detail_text}"))
