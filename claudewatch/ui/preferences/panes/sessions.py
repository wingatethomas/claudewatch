"""Sessions pane — history list with search, sort, filter."""

from __future__ import annotations

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
from claudewatch.ui.components.widgets.labels import label, pane_title, secondary_label
from claudewatch.ui.icons import sf_icon

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


def build_sessions_pane(delegate: object, w: float, h: float) -> NSView:
    """Build the Sessions pane with toolbar and scrollable rows."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))

    below_header = _add_pane_header(view, "Sessions", w, h)

    # Subtitle
    from AppKit import NSColor

    subtitle = secondary_label(_build_subtitle(), size=11.0)
    subtitle.setTextColor_(NSColor.tertiaryLabelColor())
    subtitle.setFrame_(NSMakeRect(_PAD, below_header - 14, w - _PAD * 2, 14))
    view.addSubview_(subtitle)

    # Toolbar
    toolbar_y = below_header - 14 - 8 - 30
    search = NSSearchField.alloc().initWithFrame_(NSMakeRect(_PAD, toolbar_y, 180, 24))
    search.setPlaceholderString_("Search...")
    search.setStringValue_(delegate._history_search or "")
    search.setTarget_(delegate)
    search.setAction_(objc.selector(delegate.historySearchChanged_, signature=b"v@:@"))
    view.addSubview_(search)

    sort_seg = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
        ["Date", "Name"],
        0,
        delegate,
        objc.selector(delegate.historySortChanged_, signature=b"v@:@"),
    )
    sort_seg.setFrame_(NSMakeRect(_PAD + 190, toolbar_y, 150, 24))
    sort_seg.setSegmentStyle_(NSSegmentStyleTexturedRounded)
    sort_seg.setFont_(NSFont.systemFontOfSize_(11.0))
    sel_idx = 1 if delegate._history_sort == "name" else 0
    sort_seg.setSelectedSegment_(sel_idx)
    view.addSubview_(sort_seg)

    bm_chip = NSButton.alloc().initWithFrame_(NSMakeRect(_PAD + 350, toolbar_y - 1, 36, 24))
    bm_chip.setTitle_("")
    bm_chip.setImage_(sf_icon("bookmark.fill", size=12.0))
    bm_chip.setButtonType_(1)
    bm_chip.setBezelStyle_(1)
    bm_chip.setState_(NSControlStateValueOn if delegate._history_bookmarked_only else NSControlStateValueOff)
    bm_chip.setTarget_(delegate)
    bm_chip.setAction_(objc.selector(delegate.historyBookmarkFilter_, signature=b"v@:@"))
    bm_chip.setToolTip_("Show bookmarked only")
    view.addSubview_(bm_chip)

    # Separator
    sep_y = toolbar_y - 8
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, sep_y, w - _PAD * 2, 1))
    sep.setBoxType_(2)
    view.addSubview_(sep)

    # Scroll area for rows
    scroll_y = 0
    scroll_h = sep_y - 4
    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, scroll_y, w, scroll_h))
    scroll.setHasVerticalScroller_(True)
    scroll.setAutohidesScrollers_(True)
    scroll.setDrawsBackground_(False)
    view.addSubview_(scroll)

    delegate._history_scroll = scroll
    delegate._history_inner = None

    rebuild_rows(delegate)
    return view


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
    """Build a single history row."""
    project = entry.get("project", "unknown")
    cwd = entry.get("cwd", "")
    session_id = entry.get("session_id", "")
    model_raw = entry.get("model", "")
    model = MODEL_DISPLAY_NAMES.get(model_raw, model_raw)
    ended_at = entry.get("ended_at", "")
    is_pinned = cwd in pinned_cwds
    _p = _PAD

    _bm_col = _p
    _name_col = _p + 18
    ly1 = y + h - 20

    # Bookmark toggle button
    bm_icon_name = "bookmark.fill" if is_pinned else "bookmark"
    bm_icon_img = sf_icon(bm_icon_name, size=11.0)
    if bm_icon_img:
        bm_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_bm_col, ly1 - 1, 18, 18))
        bm_btn.setImage_(bm_icon_img)
        bm_btn.setBordered_(False)
        bm_btn.setTarget_(delegate)
        if is_pinned:
            bm_btn.setAction_(objc.selector(delegate.unbookmarkSession_, signature=b"v@:@"))
            bm_btn.cell().setRepresentedObject_(cwd)
        else:
            bm_btn.setAction_(objc.selector(delegate.bookmarkSession_, signature=b"v@:@"))
            bm_btn.cell().setRepresentedObject_(f"{session_id}|{project}|{cwd}")
        bm_btn.setToolTip_("Remove bookmark" if is_pinned else "Bookmark this session")
        view.addSubview_(bm_btn)

    # Project name
    name_lbl = label(project, size=13.0, bold=True)
    name_lbl.setFrame_(NSMakeRect(_name_col, ly1, w - _name_col - 30, 18))
    view.addSubview_(name_lbl)

    # Context menu button (···)
    menu = _build_row_menu(delegate, entry, is_pinned, cwd, session_id, project, summary_svc)
    dots = NSButton.alloc().initWithFrame_(NSMakeRect(w - 30, ly1, 22, 18))
    dots.setTitle_("\u00b7\u00b7\u00b7")
    dots.setBezelStyle_(0)
    dots.setBordered_(False)
    dots.setFont_(NSFont.boldSystemFontOfSize_(11.0))
    dots.setMenu_(menu)
    dots.setTarget_(delegate)
    dots.setAction_(objc.selector(delegate.showRowMenu_, signature=b"v@:@"))
    view.addSubview_(dots)

    # Meta line: time · model · tokens
    ly2 = ly1 - 17
    meta_parts = []
    if ended_at:
        meta_parts.append(_relative_time(ended_at))
    if model:
        meta_parts.append(model)
    token_data = usage_svc.get_tokens(cwd)
    compact = format_tokens_compact(token_data)
    if compact:
        meta_parts.append(compact)
    meta_text = " \u00b7 ".join(meta_parts) if meta_parts else ""
    if meta_text:
        meta = secondary_label(meta_text, size=11.0)
        meta.setFrame_(NSMakeRect(_name_col, ly2, w - _name_col - 10, 14))
        view.addSubview_(meta)

    # Summary one-liner
    ly3 = ly2 - 16
    cached_title = summary_svc.get_cached_title(cwd) if cwd else None
    if cached_title:
        title_text = cached_title[:50]
        from AppKit import NSColor

        title_lbl = label(title_text, size=11.0, color=NSColor.tertiaryLabelColor())
        title_lbl.setFrame_(NSMakeRect(_name_col, ly3, w - _name_col - 10, 14))
        view.addSubview_(title_lbl)


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


def _add_pane_header(view: NSView, title: str, w: float, h: float) -> float:
    """Add title header, return y below it."""
    _header_h = 24
    _top = 12
    y = h - _top - _header_h
    lbl = pane_title(title)
    lbl.setFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, _header_h))
    view.addSubview_(lbl)
    return y - 8


def _relative_time(iso_str: str) -> str:  # noqa: PLR0911
    """Format a timestamp as relative time."""
    from datetime import UTC, datetime, timedelta

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
