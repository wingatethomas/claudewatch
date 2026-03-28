"""Insights pane — aggregated session metrics and tool usage breakdown."""

from __future__ import annotations

from AppKit import NSScrollView, NSView
from Foundation import NSMakeRect

from claudewatch.backend.history.dependencies import get_history_service
from claudewatch.backend.metrics.dependencies import get_metrics_service
from claudewatch.backend.usage.service import MODEL_DISPLAY_NAMES
from claudewatch.ui.components.tokens import Font, Spacing
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane
from claudewatch.ui.theme import theme


class InsightsPane(BasePane):
    """Insights pane showing aggregated session metrics."""

    @property
    def title(self) -> str:
        return "Insights"

    @property
    def subtitle(self) -> str:
        return "Aggregated metrics across all sessions"

    def build_content(self, view: NSView, content_top: float) -> None:  # noqa: PLR0915
        history = get_history_service().get_all()
        metrics_svc = get_metrics_service()
        cwds = [e.cwd for e in history if e.cwd]
        aggregated = metrics_svc.get_aggregated(cwds)

        if aggregated.total_sessions == 0:
            empty = secondary_label("No session data yet.", size=Font.BODY)
            empty.setFrame_(NSMakeRect(CONTENT_PADDING, content_top - 30, self.card_width, 18))
            view.addSubview_(empty)
            return

        # Build scroll content
        _row_h = 22
        _card_pad = Spacing.LG

        # Calculate heights
        overview_rows = 4
        overview_h = _card_pad + overview_rows * _row_h + _card_pad
        tool_rows = min(len(aggregated.top_tools), 10)
        tools_h = _card_pad + tool_rows * _row_h + _card_pad
        model_rows = len(aggregated.models)
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
            ("Sessions analyzed", str(aggregated.total_sessions)),
            ("User messages", str(aggregated.total_user_messages)),
            ("Assistant messages", str(aggregated.total_assistant_messages)),
            ("Agent spawns", str(aggregated.total_agent_spawns)),
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
        if aggregated.top_tools:
            tools_header = label("TOP TOOLS", size=Font.CAPTION, color=theme.tertiary)
            tools_header.setFrame_(NSMakeRect(CONTENT_PADDING, y - 14, self.card_width, 14))
            inner.addSubview_(tools_header)
            y -= 14 + Spacing.XS

            tools_card = card(self.card_width, tools_h)
            tools_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - tools_h, self.card_width, tools_h))
            inner.addSubview_(tools_card)
            tc = tools_card.contentView()
            ty = tools_h - _card_pad
            for tool_name, count in aggregated.top_tools:
                ty -= _row_h
                tl = label(tool_name, size=Font.SECONDARY)
                tl.setFrame_(NSMakeRect(_card_pad, ty, 200, 18))
                tc.addSubview_(tl)
                cl = label(str(count), size=Font.SECONDARY, bold=True, color=theme.secondary)
                cl.setFrame_(NSMakeRect(220, ty, 100, 18))
                tc.addSubview_(cl)
            y -= tools_h + Spacing.MD

        # Models card
        if aggregated.models:
            models_header = label("MODELS USED", size=Font.CAPTION, color=theme.tertiary)
            models_header.setFrame_(NSMakeRect(CONTENT_PADDING, y - 14, self.card_width, 14))
            inner.addSubview_(models_header)
            y -= 14 + Spacing.XS

            models_card = card(self.card_width, models_h)
            models_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - models_h, self.card_width, models_h))
            inner.addSubview_(models_card)
            mc = models_card.contentView()
            my = models_h - _card_pad
            for model_name, session_count in sorted(aggregated.models.items(), key=lambda x: -x[1]):
                my -= _row_h
                display = MODEL_DISPLAY_NAMES.get(model_name, model_name)
                ml = label(display, size=Font.SECONDARY)
                ml.setFrame_(NSMakeRect(_card_pad, my, 200, 18))
                mc.addSubview_(ml)
                sl = label(f"{session_count} sessions", size=Font.SECONDARY, color=theme.secondary)
                sl.setFrame_(NSMakeRect(220, my, 150, 18))
                mc.addSubview_(sl)

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


# Legacy function wrapper
def build_insights_pane(delegate: object, w: float, h: float) -> NSView:
    return InsightsPane(delegate, w, h).build()
