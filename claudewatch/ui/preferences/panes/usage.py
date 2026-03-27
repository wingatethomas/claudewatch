"""Usage pane — token stats and top sessions."""

from __future__ import annotations

import objc
from AppKit import NSColor, NSView
from Foundation import NSMakeRect

from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.usage.dependencies import get_usage_service
from claudewatch.ui.components.layout import VStack
from claudewatch.ui.components.widgets.buttons import Size, button
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, pane_title, secondary_label

_PAD = 24
_CARD_PAD = 16

_M = 1_000_000
_K = 1_000


def build_usage_pane(delegate: object, w: float, h: float) -> NSView:
    """Build the Usage pane with aggregated stats."""
    from datetime import UTC, datetime, timedelta

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

    card_w = w - _PAD * 2
    stack = VStack(width=w, padding=_PAD, spacing=12)
    stack.add(pane_title("Usage"), height=24)

    if not session_stats:
        stack.gap(8)
        stack.add(secondary_label("No usage data yet.", size=13.0), height=18)
        return stack.to_scroll_view(max_height=h)

    # Last 30 days section
    stack.gap(4)
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
    stack.gap(4)
    stack.add(_section_header("TOP SESSIONS BY USAGE"), height=14)

    session_stats.sort(key=lambda s: sum(s[1].values()), reverse=True)
    top = session_stats[:10]
    top_card = _build_top_sessions_card(delegate, card_w, top)
    stack.add(top_card, height=top_card.frame().size.height)

    return stack.to_scroll_view(max_height=h)


def _section_header(text: str) -> NSView:
    """Section header label."""
    return label(text, size=10.0, color=NSColor.tertiaryLabelColor())


def _build_stats_card(card_w: float, rows: list[tuple[str, int]]) -> NSView:
    """Build the stats card with label + value rows."""
    row_h = 22
    card_h = _CARD_PAD + len(rows) * row_h + _CARD_PAD
    c = card(card_w, card_h)
    cc = c.contentView()
    ry = card_h - _CARD_PAD
    for name, val in rows:
        ry -= row_h
        lbl = label(name, size=12.0, color=NSColor.secondaryLabelColor())
        lbl.setFrame_(NSMakeRect(_CARD_PAD, ry, 100, 18))
        cc.addSubview_(lbl)
        vlbl = label(_fmt(val), size=12.0, bold=True)
        vlbl.setFrame_(NSMakeRect(120, ry, card_w - 140, 18))
        cc.addSubview_(vlbl)
    return c


def _build_top_sessions_card(delegate: object, card_w: float, top: list[tuple[str, dict, str]]) -> NSView:
    """Build the top sessions card with clickable project names."""
    row_h = 24
    card_h = _CARD_PAD + len(top) * row_h + _CARD_PAD
    c = card(card_w, card_h)
    cc = c.contentView()
    ty = card_h - _CARD_PAD
    for proj, tokens, _ended in top:
        ty -= row_h
        name_btn = button(
            proj,
            target=delegate,
            action=objc.selector(delegate.jumpToSession_, signature=b"v@:@"),
            size=Size(200, 18),
            font_size=12.0,
        )
        name_btn.setBordered_(False)
        name_btn.setAlignment_(0)
        name_btn.cell().setRepresentedObject_(proj)
        name_btn.setFrame_(NSMakeRect(_CARD_PAD, ty, 200, 18))
        cc.addSubview_(name_btn)
        total_tokens = sum(tokens.values())
        tvlbl = label(_fmt(total_tokens), size=11.0, color=NSColor.secondaryLabelColor())
        tvlbl.setFrame_(NSMakeRect(card_w - _CARD_PAD - 120, ty, 120, 18))
        cc.addSubview_(tvlbl)
    return c


def _fmt(n: int) -> str:
    if n >= _M:
        return f"{n / _M:.1f}M tokens"
    if n >= _K:
        return f"{n / _K:.0f}K tokens"
    return f"{n} tokens"
