"""Usage pane — token stats and top sessions."""

from __future__ import annotations

import objc
from AppKit import NSColor, NSView
from Foundation import NSMakeRect

from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.usage.dependencies import get_usage_service
from claudewatch.ui.components.widgets.buttons import Size, button
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, pane_title, secondary_label

_PAD = 24
_CARD_PAD = 16

_M = 1_000_000
_K = 1_000


def build_usage_pane(delegate: object, w: float, h: float) -> NSView:  # noqa: PLR0915
    """Build the Usage pane with aggregated stats."""
    from datetime import UTC, datetime, timedelta

    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    y = _add_header(view, w, h)

    history = get_history_service().get_all()
    usage_svc = get_usage_service()

    # Gather stats
    session_stats: list[tuple[str, dict, str]] = []
    total = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
    cutoff = datetime.now(tz=UTC) - timedelta(days=30)

    for entry in history:
        tokens = usage_svc.get_tokens(entry.cwd)
        t_in = getattr(tokens, "input", 0) + getattr(tokens, "cache_create", 0) + getattr(tokens, "cache_read", 0)
        t_out = getattr(tokens, "output", 0)
        if t_in + t_out == 0:
            continue
        session_stats.append(
            (
                entry.project,
                {
                    "input": getattr(tokens, "input", 0),
                    "output": t_out,
                    "cache_create": getattr(tokens, "cache_create", 0),
                    "cache_read": getattr(tokens, "cache_read", 0),
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
                    total[k] += getattr(tokens, k, 0)
        except (ValueError, TypeError):
            pass

    if not session_stats:
        empty = secondary_label("No usage data yet.", size=13.0)
        empty.setFrame_(NSMakeRect(_PAD, y - 30, w - _PAD * 2, 18))
        view.addSubview_(empty)
        return view

    card_w = w - _PAD * 2

    # Last 30 days card
    y -= 12
    header_lbl = label("LAST 30 DAYS", size=10.0, color=NSColor.tertiaryLabelColor())
    header_lbl.setFrame_(NSMakeRect(_PAD, y, 200, 14))
    view.addSubview_(header_lbl)
    y -= 6

    total_in = total["input"] + total["cache_create"] + total["cache_read"]
    total_out = total["output"]
    rows = [
        ("Input", total["input"]),
        ("Output", total_out),
        ("Cache", total["cache_create"] + total["cache_read"]),
        ("Total", total_in + total_out),
    ]
    row_h = 22
    card_h = _CARD_PAD + len(rows) * row_h + _CARD_PAD
    c = card(card_w, card_h)
    c.setFrame_(NSMakeRect(_PAD, y - card_h, card_w, card_h))
    view.addSubview_(c)
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
    y -= card_h + 16

    # Top sessions
    top_header = label("TOP SESSIONS BY USAGE", size=10.0, color=NSColor.tertiaryLabelColor())
    top_header.setFrame_(NSMakeRect(_PAD, y, 300, 14))
    view.addSubview_(top_header)
    y -= 6

    session_stats.sort(key=lambda s: sum(s[1].values()), reverse=True)
    top = session_stats[:10]
    top_row_h = 24
    top_card_h = _CARD_PAD + len(top) * top_row_h + _CARD_PAD
    tc = card(card_w, top_card_h)
    tc.setFrame_(NSMakeRect(_PAD, y - top_card_h, card_w, top_card_h))
    view.addSubview_(tc)
    tcc = tc.contentView()
    ty = top_card_h - _CARD_PAD
    for proj, tokens, _ended in top:
        ty -= top_row_h
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
        tcc.addSubview_(name_btn)
        total_tokens = sum(tokens.values())
        tvlbl = label(_fmt(total_tokens), size=11.0, color=NSColor.secondaryLabelColor())
        tvlbl.setFrame_(NSMakeRect(card_w - _CARD_PAD - 120, ty, 120, 18))
        tcc.addSubview_(tvlbl)

    return view


def _add_header(view: NSView, w: float, h: float) -> float:
    y = h - 12 - 24
    lbl = pane_title("Usage")
    lbl.setFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, 24))
    view.addSubview_(lbl)
    return y - 8


def _fmt(n: int) -> str:
    if n >= _M:
        return f"{n / _M:.1f}M tokens"
    if n >= _K:
        return f"{n / _K:.0f}K tokens"
    return f"{n} tokens"
