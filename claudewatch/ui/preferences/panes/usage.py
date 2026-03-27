"""Usage pane — token stats and top sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import objc
from AppKit import NSColor, NSScrollView, NSView
from Foundation import NSMakeRect

from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.usage.dependencies import get_usage_service
from claudewatch.ui.components.layout import VStack
from claudewatch.ui.components.widgets.buttons import Size, button
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, create_pane

_PAD = 24
_CARD_PAD = 16

_M = 1_000_000
_K = 1_000


def build_usage_pane(delegate: object, w: float, h: float) -> NSView:  # noqa: PLR0915
    """Build the Usage pane with aggregated stats."""

    history = get_history_service().get_all()
    usage_svc = get_usage_service()

    # Gather stats
    session_stats: list[tuple[str, dict, str]] = []
    total = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
    cutoff = datetime.now(tz=UTC) - timedelta(days=30)

    for entry in history:
        tokens = usage_svc.get_tokens(entry.cwd)
        t_in = tokens.get("input", 0) + tokens.get("cache_create", 0) + tokens.get("cache_read", 0)
        t_out = tokens.get("output", 0)
        if t_in + t_out == 0:
            continue
        session_stats.append(
            (
                entry.project,
                {
                    "input": tokens.get("input", 0),
                    "output": t_out,
                    "cache_create": tokens.get("cache_create", 0),
                    "cache_read": tokens.get("cache_read", 0),
                },
                entry.ended_at or "",
            )
        )
        try:
            dt = datetime.fromisoformat(entry.ended_at) if entry.ended_at else None
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            if dt and dt >= cutoff:
                for k in total:
                    total[k] += tokens.get(k, 0)
        except (ValueError, TypeError):
            pass

    view, content_top = create_pane("Usage", w, h, subtitle="Token usage across all sessions")
    card_w = w - CONTENT_PADDING * 2

    if not session_stats:
        empty = secondary_label("No usage data yet.", size=13.0)
        empty.setFrame_(NSMakeRect(CONTENT_PADDING, content_top - 24, card_w, 18))
        view.addSubview_(empty)
        return view

    # Build scroll content below fixed header (minimal top padding — header already spaced)
    stack = VStack(width=w, padding=8, spacing=8)
    stack.add(_section_header("LAST 30 DAYS"), height=14)

    total_in = total["input"] + total["cache_create"] + total["cache_read"]
    total_out = total["output"]
    stats_card = _build_stats_card(
        card_w,
        [
            ("Input", total["input"]),
            ("Output", total_out),
            ("Cache", total["cache_create"] + total["cache_read"]),
            ("Total", total_in + total_out),
        ],
    )
    stack.add(stats_card, height=stats_card.frame().size.height)

    # Top sessions section
    stack.add(_section_header("TOP SESSIONS BY USAGE"), height=14)

    session_stats.sort(key=lambda s: sum(s[1].values()), reverse=True)
    top = session_stats[:10]
    top_card = _build_top_sessions_card(delegate, card_w, top)
    stack.add(top_card, height=top_card.frame().size.height)

    # Place stack content below fixed header
    scroll_h = content_top
    if stack.content_height <= scroll_h:
        content_view = stack.to_view(min_height=scroll_h)
        view.addSubview_(content_view)
    else:
        inner = stack.to_view()
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, w, scroll_h))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        scroll.setDocumentView_(inner)
        inner.scrollPoint_((0, inner.frame().size.height))
        view.addSubview_(scroll)

    return view


def _section_header(text: str) -> NSView:
    """Section header label."""
    return label(text, size=10.0, color=NSColor.tertiaryLabelColor())


def _build_stats_card(card_w: float, rows: list[tuple[str, int]]) -> NSView:
    """Build the stats card with label + value rows."""
    row_h = 22
    card_h = _CARD_PAD + len(rows) * row_h + _CARD_PAD
    stats_card = card(card_w, card_h)
    content = stats_card.contentView()
    row_y = card_h - _CARD_PAD
    for name, val in rows:
        row_y -= row_h
        name_label = label(name, size=12.0, color=NSColor.secondaryLabelColor())
        name_label.setFrame_(NSMakeRect(_CARD_PAD, row_y, 100, 18))
        content.addSubview_(name_label)
        value_label = label(_fmt(val), size=12.0, bold=True)
        value_label.setFrame_(NSMakeRect(120, row_y, card_w - 140, 18))
        content.addSubview_(value_label)
    return stats_card


def _build_top_sessions_card(delegate: object, card_w: float, top: list[tuple[str, dict, str]]) -> NSView:
    """Build the top sessions card with clickable project names."""
    row_h = 24
    card_h = _CARD_PAD + len(top) * row_h + _CARD_PAD
    top_card = card(card_w, card_h)
    content = top_card.contentView()
    row_y = card_h - _CARD_PAD
    for project, tokens, _ended in top:
        row_y -= row_h
        project_btn = button(
            project,
            target=delegate,
            action=objc.selector(delegate.jumpToSession_, signature=b"v@:@"),
            size=Size(200, 18),
            font_size=12.0,
        )
        project_btn.setBordered_(False)
        project_btn.setAlignment_(0)
        project_btn.cell().setRepresentedObject_(project)
        project_btn.setFrame_(NSMakeRect(_CARD_PAD, row_y, 200, 18))
        content.addSubview_(project_btn)
        token_count = sum(tokens.values())
        token_label = label(_fmt(token_count), size=11.0, color=NSColor.secondaryLabelColor())
        token_label.setFrame_(NSMakeRect(card_w - _CARD_PAD - 120, row_y, 120, 18))
        content.addSubview_(token_label)
    return top_card


def _fmt(n: int) -> str:
    if n >= _M:
        return f"{n / _M:.1f}M tokens"
    if n >= _K:
        return f"{n / _K:.0f}K tokens"
    return f"{n} tokens"
