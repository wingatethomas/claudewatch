"""Sessions pane — history list with search, sort, filter."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import objc
from AppKit import (
    NSBox,
    NSButton,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSMenu,
    NSMenuItem,
    NSScrollView,
    NSSearchField,
    NSSegmentedControl,
    NSSegmentStyleTexturedRounded,
    NSView,
)
from Foundation import NSMakeRect

from claudewatch.backend.bookmark.dependencies import get_bookmark_service
from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.summary.dependencies import get_summary_service
from claudewatch.backend.usage.dependencies import get_usage_service
from claudewatch.backend.usage.service import format_tokens_compact, model_display_name
from claudewatch.ui.components.composites.session_row import build_session_row
from claudewatch.ui.components.tokens import Font, Spacing
from claudewatch.ui.components.widgets.labels import secondary_label
from claudewatch.ui.icons import sf_icon
from claudewatch.ui.preferences.panes.common import BasePane
from claudewatch.ui.theme import theme

_PAD = 24
_CARD_PAD = 16
_ROW_H = 54


def _build_subtitle() -> str:
    """Build subtitle with counts and date range of recorded sessions."""
    entries = get_history_service().get_all()
    if not entries:
        return "No sessions recorded yet"
    parts = [f"{len(entries)} session" + ("s" if len(entries) != 1 else "")]
    week_cutoff = (datetime.now(tz=UTC) - timedelta(days=7)).isoformat()
    this_week = sum(1 for e in entries if (e.ended_at or "") >= week_cutoff)
    if this_week:
        parts.append(f"{this_week} this week")
    oldest = min((e.ended_at or "" for e in entries if e.ended_at), default="")
    if len(oldest) >= 10:
        parts.append(f"since {oldest[:10]}")
    return " · ".join(parts)


class SessionsPane(BasePane):
    """Sessions pane with toolbar and scrollable history rows."""

    @property
    def title(self) -> str:
        return "Sessions"

    @property
    def subtitle(self) -> str:
        return _build_subtitle()

    def build_content(self, view: NSView, content_top: float) -> None:
        # Toolbar
        toolbar_y = content_top - 30
        search_field = NSSearchField.alloc().initWithFrame_(NSMakeRect(_PAD, toolbar_y, 180, 24))
        search_field.setPlaceholderString_("Search...")
        search_field.setStringValue_(self.delegate._history_search or "")
        search_field.setTarget_(self.delegate)
        search_field.setAction_(objc.selector(self.delegate.historySearchChanged_, signature=b"v@:@"))
        view.addSubview_(search_field)

        sort_control = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            ["Date", "Name"],
            0,
            self.delegate,
            objc.selector(self.delegate.historySortChanged_, signature=b"v@:@"),
        )
        sort_control.setFrame_(NSMakeRect(_PAD + 190, toolbar_y, 150, 24))
        sort_control.setSegmentStyle_(NSSegmentStyleTexturedRounded)
        sort_control.setFont_(NSFont.systemFontOfSize_(Font.SMALL))
        sort_index = 1 if self.delegate._history_sort == "name" else 0
        sort_control.setSelectedSegment_(sort_index)
        view.addSubview_(sort_control)

        bookmark_filter = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD + 350, toolbar_y - 1, 36, 24))
        bookmark_filter.setTitle_("")
        bookmark_filter.setImage_(sf_icon("bookmark.fill", size=Font.SECONDARY))
        bookmark_filter.setButtonType_(1)
        bookmark_filter.setBezelStyle_(1)
        bookmark_filter.setState_(
            NSControlStateValueOn if self.delegate._history_bookmarked_only else NSControlStateValueOff
        )
        bookmark_filter.setTarget_(self.delegate)
        bookmark_filter.setAction_(objc.selector(self.delegate.historyBookmarkFilter_, signature=b"v@:@"))
        bookmark_filter.setToolTip_("Show bookmarked only")
        view.addSubview_(bookmark_filter)

        clear_stale = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD + 392, toolbar_y - 1, 36, 24))
        clear_stale.setTitle_("")
        clear_stale.setImage_(sf_icon("trash", size=Font.SECONDARY))
        clear_stale.setBezelStyle_(1)
        clear_stale.setTarget_(self.delegate)
        clear_stale.setAction_(objc.selector(self.delegate.historyClearStale_, signature=b"v@:@"))
        clear_stale.setToolTip_("Clear entries whose session logs are gone")
        view.addSubview_(clear_stale)

        # Separator
        separator_y = toolbar_y - Spacing.SM
        toolbar_separator = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, separator_y, self.width - _PAD * 2, 1))
        toolbar_separator.setBoxType_(2)
        view.addSubview_(toolbar_separator)

        # Scroll area for rows
        scroll_h = separator_y - Spacing.XS
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, self.width, scroll_h))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        view.addSubview_(scroll)

        self.delegate._history_scroll = scroll
        self.delegate._history_inner = None

        rebuild_rows(self.delegate)


# Legacy function interface for window.py
def build_sessions_pane(delegate: object, w: float, h: float) -> NSView:
    """Build the Sessions pane."""
    return SessionsPane(delegate, w, h).build()


def rebuild_rows(delegate: object) -> None:
    """Rebuild the history row list based on current filter/sort state."""

    scroll = delegate._history_scroll
    if scroll is None:
        return

    w = scroll.frame().size.width
    history_svc = get_history_service()
    entries = [e.to_dict() for e in history_svc.get_all()]
    bookmark_svc = get_bookmark_service()
    summary_svc = get_summary_service()
    usage_svc = get_usage_service()

    _queue_missing_titles(entries, summary_svc, history_svc)

    # Filter: bookmarked only
    if delegate._history_bookmarked_only:
        entries = [e for e in entries if bookmark_svc.is_bookmarked(e.get("session_id", ""), e.get("cwd", ""))]

    # Search filter
    search = delegate._history_search
    if search:
        filtered = []
        for e in entries:
            proj = e.get("project", "").lower()
            if search in proj:
                filtered.append(e)
                continue
            cached = summary_svc.get_cached(e.get("cwd", ""), e.get("session_id", ""))
            if cached and search in cached.lower():
                filtered.append(e)
        entries = filtered

    # Sort
    if delegate._history_sort == "name":
        entries.sort(key=lambda e: e.get("project", "").lower(), reverse=not delegate._history_sort_asc)
    else:
        entries.sort(key=lambda e: e.get("ended_at", ""), reverse=not delegate._history_sort_asc)

    # Build rows
    total_h = max(scroll.frame().size.height, len(entries) * _ROW_H)
    inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, total_h))

    if not entries:
        empty_label = secondary_label("No sessions found", size=13.0)
        empty_label.setTextColor_(theme.tertiary)
        empty_label.setAlignment_(1)  # NSTextAlignmentCenter
        empty_label.setFrame_(NSMakeRect(0, total_h // 2, w, 18))
        inner.addSubview_(empty_label)
    else:
        project_labels = disambiguate_projects(entries)
        y = total_h
        for entry in entries:
            y -= _ROW_H
            display_project = project_labels.get(entry.get("cwd", ""), entry.get("project", "unknown"))
            _add_row(
                inner,
                delegate,
                entry,
                0,
                y,
                w,
                _ROW_H,
                bookmark_svc,
                usage_svc,
                summary_svc,
                display_project,
                stale=not history_svc.logs_exist(entry.get("cwd", ""), entry.get("session_id", "")),
            )

    scroll.setDocumentView_(inner)
    inner.scrollPoint_((0, total_h))  # scroll to top (newest first)
    delegate._history_inner = inner


def _queue_missing_titles(entries: list[dict], summary_svc: object, history_svc: object, limit: int = 30) -> None:
    """Queue background title extraction for entries with nothing cached yet.

    The summary thread fills them in; rows pick titles up on the next rebuild.
    """
    queued = 0
    for e in entries:
        if queued >= limit:
            return
        cwd, sid = e.get("cwd", ""), e.get("session_id", "")
        if cwd and summary_svc.get_cached(cwd, sid) is None and history_svc.logs_exist(cwd, sid):  # type: ignore[attr-defined]
            summary_svc.track_session(cwd, session_id=sid)  # type: ignore[attr-defined]
            queued += 1


def disambiguate_projects(entries: list[dict]) -> dict[str, str]:
    """Build a cwd -> display-name map that disambiguates duplicate basenames.

    When two history entries share the same ``project`` basename (e.g. multiple
    repos with an ``api`` subdirectory), prepend the parent directory so each
    row carries enough context to be identifiable. Unique basenames are kept
    as-is.
    """
    by_name: dict[str, list[str]] = {}
    for entry in entries:
        name = entry.get("project", "")
        cwd = entry.get("cwd", "")
        if not cwd:
            continue
        by_name.setdefault(name, []).append(cwd)

    labels: dict[str, str] = {}
    for name, cwds in by_name.items():
        if len(cwds) <= 1:
            for cwd in cwds:
                labels[cwd] = name or "unknown"
            continue
        for cwd in cwds:
            parent = os.path.basename(os.path.dirname(cwd))
            labels[cwd] = f"{parent}/{name}" if parent else (name or "unknown")
    return labels


def _resolve_model_label(model_raw: str, cwd: str, usage_svc: object) -> str:
    """Map a raw model id to its display name, falling back to live JSONL lookup.

    History rows occasionally have an empty ``model`` field — sessions seeded
    before any assistant message was written, or older entries missing the
    field. When that happens, ask the usage service for the latest model
    recorded on disk so the row still shows something useful.
    """
    if model_raw:
        return model_display_name(model_raw)
    if not cwd:
        return ""
    try:
        fallback = usage_svc.get_model(cwd)  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return ""
    return model_display_name(fallback)


def _add_row(  # noqa: PLR0912, PLR0913, PLR0915, ARG001
    view: NSView,
    delegate: object,
    entry: dict,
    x: float,
    y: float,
    w: float,
    h: float,
    bookmark_svc: object,
    usage_svc: object,
    summary_svc: object,
    display_project: str = "",
    *,
    stale: bool = False,
) -> None:
    """Build a single history row using the SessionRow composite."""

    raw_project = entry.get("project", "unknown")
    project = display_project or raw_project
    cwd = entry.get("cwd", "")
    session_id = entry.get("session_id", "")
    model_raw = entry.get("model", "")
    model = _resolve_model_label(model_raw, cwd, usage_svc)
    ended_at = entry.get("ended_at", "")
    is_pinned = bookmark_svc.is_bookmarked(session_id, cwd)  # type: ignore[attr-defined]

    # Build context menu — use raw project as the stable identity for action payloads.
    row_menu = _build_row_menu(delegate, entry, is_pinned, cwd, session_id, raw_project, summary_svc)

    # Gather display data
    token_data = usage_svc.get_tokens(cwd)
    token_compact = format_tokens_compact(token_data)
    cached_title = summary_svc.get_cached(cwd, session_id) if cwd else ""

    # Bookmark callback wiring — payload carries the raw project as identity.
    if is_pinned:
        bookmark_action = objc.selector(delegate.unbookmarkSession_, signature=b"v@:@")
        bookmark_rep = f"{session_id}|{cwd}"
    else:
        bookmark_action = objc.selector(delegate.bookmarkSession_, signature=b"v@:@")
        bookmark_rep = f"{session_id}|{raw_project}|{cwd}"

    row = build_session_row(
        project=project,
        cwd=cwd,
        model=model,
        ended_at=_relative_time(ended_at),
        bookmarked=is_pinned,
        stale=stale,
        width=w,
        height=h,
        summary_title=cached_title or "",
        token_compact=token_compact,
        on_bookmark_toggle=bookmark_action,
        on_menu_click=objc.selector(delegate.showRowMenu_, signature=b"v@:@"),
        bookmark_represented_object=bookmark_rep,
        menu=row_menu,
        delegate=delegate,
    )
    row.setFrame_(NSMakeRect(x, y, w, h))
    view.addSubview_(row)


def _build_row_menu(  # noqa: PLR0913, ARG001
    delegate: object,
    entry: dict,
    is_pinned: bool,
    cwd: str,
    session_id: str,
    project: str,
    summary_svc: object,
) -> NSMenu:
    """Build context menu for a history row."""
    menu = NSMenu.alloc().init()

    # Summary bullets
    bullets = summary_svc.get_cached_summary(cwd) if cwd else None
    if bullets:
        for line in bullets.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            words = stripped.split()
            wrapped = ""
            for word in words:
                if wrapped and len(wrapped) + 1 + len(word) > 55:
                    mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(f"  {wrapped}", None, "")
                    mi.setEnabled_(False)
                    menu.addItem_(mi)
                    wrapped = f"    {word}"
                else:
                    wrapped = f"{wrapped} {word}" if wrapped else word
            if wrapped:
                mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(f"  {wrapped}", None, "")
                mi.setEnabled_(False)
                menu.addItem_(mi)
        menu.addItem_(NSMenuItem.separatorItem())

    # Actions
    def _add_action(title: str, action: object, rep_obj: str) -> None:
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        mi.setTarget_(delegate)
        mi.setAction_(objc.selector(action, signature=b"v@:@"))
        mi.setRepresentedObject_(rep_obj)
        menu.addItem_(mi)

    if session_id:
        _add_action("Resume", delegate.resumeSession_, f"{session_id}|{cwd}")
    _add_action("Activity", delegate.viewActivity_, f"{project}|{cwd}")
    menu.addItem_(NSMenuItem.separatorItem())

    if is_pinned:
        _add_action("Remove Bookmark", delegate.unbookmarkSession_, f"{session_id}|{cwd}")
    else:
        _add_action("Bookmark", delegate.bookmarkSession_, f"{session_id}|{project}|{cwd}")

    _add_action("Copy Path", delegate.copyCwd_, cwd)
    _add_action("Open in Finder", delegate.revealInFinder_, cwd)
    menu.addItem_(NSMenuItem.separatorItem())
    _add_action("Delete", delegate.deleteHistoryEntry_, cwd)

    return menu


def _relative_time(iso_str: str) -> str:  # noqa: PLR0911
    """Format a timestamp as relative time."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        now = datetime.now(tz=UTC)
        delta = now - dt
        if delta < timedelta(minutes=1):
            return "just now"
        if delta < timedelta(hours=1):
            return f"{int(delta.total_seconds() / 60)}m ago"
        if delta < timedelta(hours=24):
            return f"{int(delta.total_seconds() / 3600)}h ago"
        if delta < timedelta(days=2):
            return "yesterday"
        if delta < timedelta(days=7):
            return f"{int(delta.days)}d ago"
        return dt.strftime("%b %-d")
    except (ValueError, TypeError):
        return ""
