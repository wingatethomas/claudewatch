"""Graph pane — project overview, workflow patterns, and file hotspots."""

from __future__ import annotations

import logging
import threading

from AppKit import NSScrollView, NSView
from Foundation import NSMakeRect

from claudewatch.backend.analytics.dependencies import get_analytics_service
from claudewatch.backend.graph.dependencies import get_graph_service
from claudewatch.backend.graph.models import ProjectGraphResult, WorkflowPattern
from claudewatch.ui.components.layout import VStack
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane
from claudewatch.ui.theme import theme

log = logging.getLogger("claudewatch")

_CARD_PAD = 16
_ROW_H = 22


class GraphPane(BasePane):
    """Graph pane showing code knowledge graph insights."""

    _bootstrap_running = False

    @property
    def title(self) -> str:
        return "Graph"

    @property
    def subtitle(self) -> str:
        return "Code knowledge graph"

    def build_content(self, view: NSView, content_top: float) -> None:
        graph_svc = get_graph_service()
        overview = graph_svc.queries.project_graph_all()

        if overview.sessions == 0:
            empty = secondary_label("Graph data will appear after the first background scan.", size=13.0)
            empty.setFrame_(NSMakeRect(CONTENT_PADDING, content_top - 30, self.card_width, 18))
            view.addSubview_(empty)
            if not GraphPane._bootstrap_running:
                GraphPane._bootstrap_running = True
                threading.Thread(target=self._bootstrap, daemon=True).start()
            return

        stack = VStack(width=self.card_width, padding=0, spacing=8)

        # Overview card
        stack.add(_section_header("OVERVIEW"), height=14)
        overview_card = _build_overview_card(self.card_width, overview)
        stack.add(overview_card, height=overview_card.frame().size.height)

        # Workflow patterns
        patterns = graph_svc.queries.workflow_patterns_all(limit=8)
        if patterns:
            stack.add(_section_header("WORKFLOW PATTERNS"), height=14)
            patterns_card = _build_patterns_card(self.card_width, patterns)
            stack.add(patterns_card, height=patterns_card.frame().size.height)

        # File hotspots (from analytics, not graph — doesn't need AST indexing)
        hotspots = get_analytics_service().queries.hotspot_files_global(min_sessions=2, limit=10)
        if hotspots:
            stack.add(_section_header("FILE HOTSPOTS"), height=14)
            hotspots_card = _build_hotspots_card(self.card_width, hotspots)
            stack.add(hotspots_card, height=hotspots_card.frame().size.height)

        # Place in scroll
        scroll_h = content_top
        if stack.content_height <= scroll_h:
            content_view = stack.to_view(min_height=scroll_h)
            content_view.setFrame_(NSMakeRect(CONTENT_PADDING, 0, self.card_width, scroll_h))
            view.addSubview_(content_view)
        else:
            inner = stack.to_view()
            scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(CONTENT_PADDING, 0, self.card_width, scroll_h))
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            scroll.setDrawsBackground_(False)
            scroll.setDocumentView_(inner)
            inner.scrollPoint_((0, inner.frame().size.height))
            view.addSubview_(scroll)

    def _bootstrap(self) -> None:
        try:
            get_graph_service().ingest_sessions()
        except Exception:
            log.exception("graph bootstrap failed")
        finally:
            GraphPane._bootstrap_running = False


def _section_header(text: str) -> NSView:
    return label(text, size=10.0, color=theme.tertiary)


def _build_overview_card(card_w: float, overview: ProjectGraphResult) -> NSView:
    rows = [
        ("Sessions", str(overview.sessions)),
        ("Actions", str(overview.actions)),
        ("Files", str(overview.files)),
        ("Symbols", str(overview.symbols)),
    ]
    card_h = _CARD_PAD + len(rows) * _ROW_H + _CARD_PAD
    overview_card = card(card_w, card_h)
    content = overview_card.contentView()
    ry = card_h - _CARD_PAD
    for name, value in rows:
        ry -= _ROW_H
        name_label = label(name, size=12.0, color=theme.secondary)
        name_label.setFrame_(NSMakeRect(_CARD_PAD, ry, 200, 18))
        content.addSubview_(name_label)
        value_label = label(value, size=12.0, bold=True)
        value_label.setFrame_(NSMakeRect(220, ry, card_w - 240, 18))
        content.addSubview_(value_label)
    return overview_card


def _build_patterns_card(card_w: float, patterns: list[WorkflowPattern]) -> NSView:
    card_h = _CARD_PAD + len(patterns) * _ROW_H + _CARD_PAD
    patterns_card = card(card_w, card_h)
    content = patterns_card.contentView()
    ry = card_h - _CARD_PAD
    for pattern in patterns:
        ry -= _ROW_H
        sequence_label = label(f"{pattern.first} → {pattern.then}", size=12.0)
        sequence_label.setFrame_(NSMakeRect(_CARD_PAD, ry, 250, 18))
        content.addSubview_(sequence_label)
        count_label = label(str(pattern.frequency), size=12.0, bold=True, color=theme.secondary)
        count_label.setFrame_(NSMakeRect(card_w - _CARD_PAD - 80, ry, 80, 18))
        content.addSubview_(count_label)
    return patterns_card


def _build_hotspots_card(card_w: float, hotspots: list[object]) -> NSView:
    card_h = _CARD_PAD + len(hotspots) * _ROW_H + _CARD_PAD
    hotspots_card = card(card_w, card_h)
    content = hotspots_card.contentView()
    ry = card_h - _CARD_PAD
    _max_path = 45
    for hotspot in hotspots:
        ry -= _ROW_H
        path = hotspot.path
        short_path = "…" + path[-(_max_path - 1) :] if len(path) > _max_path else path
        path_label = label(short_path, size=11.0)
        path_label.setFrame_(NSMakeRect(_CARD_PAD, ry, card_w - _CARD_PAD - 100, 18))
        content.addSubview_(path_label)
        count_text = f"{hotspot.session_count} sessions"
        count_label = label(count_text, size=11.0, color=theme.secondary)
        count_label.setFrame_(NSMakeRect(card_w - _CARD_PAD - 90, ry, 90, 18))
        content.addSubview_(count_label)
    return hotspots_card
