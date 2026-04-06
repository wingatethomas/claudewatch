"""Insights pane — aggregated session metrics and tool usage breakdown."""

from __future__ import annotations

import logging
import threading

from AppKit import NSScrollView, NSView
from Foundation import NSMakeRect

from claudewatch.backend.analytics.dependencies import get_analytics_service
from claudewatch.backend.usage.service import MODEL_DISPLAY_NAMES
from claudewatch.ui.components.tokens import Font, Spacing
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane
from claudewatch.ui.theme import theme

log = logging.getLogger("claudewatch")


class InsightsPane(BasePane):
    """Insights pane showing aggregated session metrics."""

    @property
    def title(self) -> str:
        return "Insights"

    @property
    def subtitle(self) -> str:
        return "Aggregated metrics across all sessions"

    def build_content(self, view: NSView, content_top: float) -> None:  # noqa: PLR0915
        analytics_svc = get_analytics_service()
        summary = analytics_svc.queries.summary()

        if summary.total_sessions == 0:
            empty = secondary_label("No session data yet.", size=Font.BODY)
            empty.setFrame_(NSMakeRect(CONTENT_PADDING, content_top - 30, self.card_width, 18))
            view.addSubview_(empty)
            # Bootstrap: kick off a first scan in background
            threading.Thread(target=self._bootstrap_scan, daemon=True).start()
            return

        tools = analytics_svc.queries.tool_usage(limit=10)
        models = analytics_svc.queries.model_distribution()

        # Build scroll content
        _row_h = 22
        _card_pad = Spacing.LG

        # Calculate heights
        overview_rows = 4
        overview_h = _card_pad + overview_rows * _row_h + _card_pad
        tool_rows = min(len(tools), 10)
        tools_h = _card_pad + tool_rows * _row_h + _card_pad
        model_rows = len(models)
        models_h = _card_pad + model_rows * _row_h + _card_pad
        content_h = overview_h + tools_h + models_h + Spacing.XL * 4

        scroll_h = content_top
        inner_h = max(scroll_h, content_h)
        inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self.width, inner_h))
        y = inner_h

        # Overview card
        y -= Spacing.SM
        overview_header = label("OVERVIEW", size=Font.CAPTION, color=theme.tertiary)
        overview_header.setFrame_(NSMakeRect(CONTENT_PADDING, y - 14, self.card_width, 14))
        inner.addSubview_(overview_header)
        y -= 14 + Spacing.XS

        overview_card = card(self.card_width, overview_h)
        overview_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - overview_h, self.card_width, overview_h))
        inner.addSubview_(overview_card)
        content = overview_card.contentView()
        ry = overview_h - _card_pad
        for name, value in [
            ("Sessions", str(summary.total_sessions)),
            ("Messages", str(summary.total_messages)),
            ("Tool calls", str(summary.total_tools)),
            ("Agents spawned", str(summary.total_agents)),
        ]:
            ry -= _row_h
            name_label = label(name, size=Font.SECONDARY, color=theme.secondary)
            name_label.setFrame_(NSMakeRect(_card_pad, ry, 200, 18))
            content.addSubview_(name_label)
            value_label = label(value, size=Font.SECONDARY, bold=True)
            value_label.setFrame_(NSMakeRect(220, ry, self.card_width - 240, 18))
            content.addSubview_(value_label)
        y -= overview_h + Spacing.MD

        # Top tools card
        if tools:
            tools_header = label("TOP TOOLS", size=Font.CAPTION, color=theme.tertiary)
            tools_header.setFrame_(NSMakeRect(CONTENT_PADDING, y - 14, self.card_width, 14))
            inner.addSubview_(tools_header)
            y -= 14 + Spacing.XS

            tools_card = card(self.card_width, tools_h)
            tools_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - tools_h, self.card_width, tools_h))
            inner.addSubview_(tools_card)
            tools_content = tools_card.contentView()
            ty = tools_h - _card_pad
            for tool in tools:
                ty -= _row_h
                tool_label = label(tool.name, size=Font.SECONDARY)
                tool_label.setFrame_(NSMakeRect(_card_pad, ty, 200, 18))
                tools_content.addSubview_(tool_label)
                count_label = label(str(tool.count), size=Font.SECONDARY, bold=True, color=theme.secondary)
                count_label.setFrame_(NSMakeRect(220, ty, 100, 18))
                tools_content.addSubview_(count_label)
            y -= tools_h + Spacing.MD

        # Models card
        if models:
            models_header = label("MODELS USED", size=Font.CAPTION, color=theme.tertiary)
            models_header.setFrame_(NSMakeRect(CONTENT_PADDING, y - 14, self.card_width, 14))
            inner.addSubview_(models_header)
            y -= 14 + Spacing.XS

            models_card = card(self.card_width, models_h)
            models_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - models_h, self.card_width, models_h))
            inner.addSubview_(models_card)
            models_content = models_card.contentView()
            my = models_h - _card_pad
            for model_entry in models:
                my -= _row_h
                display = MODEL_DISPLAY_NAMES.get(model_entry.name, model_entry.name)
                model_label = label(display, size=Font.SECONDARY)
                model_label.setFrame_(NSMakeRect(_card_pad, my, 200, 18))
                models_content.addSubview_(model_label)
                session_label = label(
                    f"{model_entry.count} sessions",
                    size=Font.SECONDARY,
                    color=theme.secondary,
                )
                session_label.setFrame_(NSMakeRect(220, my, 150, 18))
                models_content.addSubview_(session_label)

        # Place in scroll
        if content_h <= scroll_h:
            inner.setFrame_(NSMakeRect(0, 0, self.width, scroll_h))
            view.addSubview_(inner)
        else:
            scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, self.width, scroll_h))
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            scroll.setDrawsBackground_(False)
            scroll.setDocumentView_(inner)
            inner.scrollPoint_((0, inner_h))
            view.addSubview_(scroll)

    def _bootstrap_scan(self) -> None:
        try:
            get_analytics_service().incremental_scan()
        except Exception:
            log.exception("insights bootstrap scan failed")


# Legacy function wrapper
def build_insights_pane(delegate: object, w: float, h: float) -> NSView:
    return InsightsPane(delegate, w, h).build()
