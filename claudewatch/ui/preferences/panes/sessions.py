"""Sessions pane — history list with search, sort, filter."""

from __future__ import annotations

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
from claudewatch.backend.usage.service import MODEL_DISPLAY_NAMES, format_tokens_compact
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
    """Build subtitle showing date range of recorded sessions."""
    entries = get_history_service().get_all()
    if not entries:
        return "No sessions recorded yet"
    oldest = min((e.ended_at or "" for e in entries), default="")
    return f"Since {oldest[:10]}" if oldest and len(oldest) >= 10 else f"{len(entries)} sessions"


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
    entries = [e.to_dict() for e in get_history_service().get_all()]
    pinned_cwds = get_bookmark_service().get_bookmarked_cwds()
    summary_svc = get_summary_service()
    usage_svc = get_usage_service()

    # Filter: bookmarked only
    if delegate._history_bookmarked_only:
        entries = [e for e in entries if e.get("cwd", "") in pinned_cwds]

    # Search filter
    search = delegate._history_search
    if search:
        filtered = []
        for e in entries:
            proj = e.get("project", "").lower()
            if search in proj:
                filtered.append(e)
                continue
            cached = summary_svc.get_cached(e.get("cwd", ""))
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
        y = total_h
        for entry in entries:
            y -= _ROW_H
            _add_row(inner, delegate, entry, 0, y, w, _ROW_H, pinned_cwds, usage_svc, summary_svc)

    scroll.setDocumentView_(inner)
    inner.scrollPoint_((0, total_h))  # scroll to top (newest first)
    delegate._history_inner = inner


def _add_row(  # noqa: PLR0912, PLR0913, PLR0915, ARG001
    view: NSView,
    delegate: object,
    entry: dict,
    x: float,
    y: float,
    w: float,
    h: float,
    pinned_cwds: set[str],
    usage_svc: object,
    summary_svc: object,
) -> None:
    """Build a single history row using the SessionRow composite."""

    project = entry.get("project", "unknown")
    cwd = entry.get("cwd", "")
    session_id = entry.get("session_id", "")
    model_raw = entry.get("model", "")
    model = MODEL_DISPLAY_NAMES.get(model_raw, model_raw)
    ended_at = entry.get("ended_at", "")
    is_pinned = cwd in pinned_cwds

    # Build context menu
    row_menu = _build_row_menu(delegate, entry, is_pinned, cwd, session_id, project, summary_svc)

    # Gather display data
    token_data = usage_svc.get_tokens(cwd)
    token_compact = format_tokens_compact(token_data)
    cached_title = summary_svc.get_cached_title(cwd) if cwd else ""

    # Bookmark callback wiring
    if is_pinned:
        bookmark_action = objc.selector(delegate.unbookmarkSession_, signature=b"v@:@")
        bookmark_rep = cwd
    else:
        bookmark_action = objc.selector(delegate.bookmarkSession_, signature=b"v@:@")
        bookmark_rep = f"{session_id}|{project}|{cwd}"

    row = build_session_row(
        project=project,
        cwd=cwd,
        model=model,
        ended_at=_relative_time(ended_at),
        bookmarked=is_pinned,
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
        _add_action("Remove Bookmark", delegate.unbookmarkSession_, cwd)
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
