"""Graph pane — change impact analysis and code intelligence."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import webbrowser

from AppKit import NSScrollView, NSView
from Foundation import NSMakeRect

from claudewatch.backend.analytics.dependencies import get_analytics_service
from claudewatch.backend.core import features
from claudewatch.backend.graph.dependencies import get_graph_service
from claudewatch.ui.components.layout import VStack
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane
from claudewatch.ui.theme import theme

log = logging.getLogger("claudewatch")

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "graph_assets")
_CARD_PAD = 16
_ROW_H = 22


class GraphPane(BasePane):
    """Graph pane showing change impact analysis."""

    _bootstrap_running = False

    @property
    def title(self) -> str:
        return "Graph"

    @property
    def subtitle(self) -> str:
        return "Change impact analysis"

    def build_content(self, view: NSView, content_top: float) -> None:  # noqa: PLR0915
        graph_svc = get_graph_service()
        analytics_svc = get_analytics_service()
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

        # Overview
        stack.add(_section_header("OVERVIEW"), height=14)
        overview_rows = [
            ("Sessions tracked", str(overview.sessions)),
            ("Actions recorded", str(overview.actions)),
            ("Files touched", str(overview.files)),
            ("Symbols indexed", str(overview.symbols)),
        ]
        overview_card = _build_rows_card(self.card_width, overview_rows)
        stack.add(overview_card, height=overview_card.frame().size.height)

        # Code indexing status
        indexing_enabled = features.is_enabled("code_indexing")
        if not indexing_enabled:
            stack.gap(4)
            hint = secondary_label("Enable Code Indexing in Settings for function-level impact analysis.", size=11.0)
            stack.add(hint, height=16)

        # Recent edits → functions (only if code indexing is on and symbols exist)
        if indexing_enabled and overview.symbols > 0:
            recent_edits = graph_svc.queries.recent_edits_with_symbols(limit=10)
            if recent_edits:
                stack.add(_section_header("RECENT EDITS → FUNCTIONS"), height=14)
                edit_card = _build_edits_card(self.card_width, recent_edits)
                stack.add(edit_card, height=edit_card.frame().size.height)

        # Function hotspots (graph-based, needs code indexing)
        if indexing_enabled and overview.symbols > 0:
            hotspots = graph_svc.queries.function_hotspots(
                project=graph_svc.queries.active_project_paths()[0] if graph_svc.queries.active_project_paths() else "",
                limit=10,
            )
            if hotspots:
                stack.add(_section_header("FUNCTION HOTSPOTS"), height=14)
                hotspot_rows = [(h.qualified_name.rsplit(":", 1)[-1], f"{h.edits} edits") for h in hotspots]
                hotspot_card = _build_rows_card(self.card_width, hotspot_rows)
                stack.add(hotspot_card, height=hotspot_card.frame().size.height)

        # File hotspots (analytics-based, always available)
        file_hotspots = analytics_svc.queries.hotspot_files_global(min_sessions=2, limit=10)
        if file_hotspots:
            stack.add(_section_header("FILE HOTSPOTS"), height=14)
            file_rows = [(_shorten_path(h.path), f"{h.session_count} sessions") for h in file_hotspots]
            file_card = _build_rows_card(self.card_width, file_rows)
            stack.add(file_card, height=file_card.frame().size.height)

        # Workflow patterns
        patterns = graph_svc.queries.workflow_patterns_all(limit=8)
        if patterns:
            stack.add(_section_header("WORKFLOW PATTERNS"), height=14)
            pattern_rows = [(f"{p.first} → {p.then}", str(p.frequency)) for p in patterns]
            pattern_card = _build_rows_card(self.card_width, pattern_rows)
            stack.add(pattern_card, height=pattern_card.frame().size.height)

        # Open in browser link
        if indexing_enabled and overview.symbols > 0:
            stack.gap(8)
            browser_label = label("Open impact graph in browser →", size=12.0, color=theme.accent)
            stack.add(browser_label, height=18)
            # Fire browser open in background to not block pane render
            threading.Thread(target=self._open_impact_in_browser, daemon=True).start()

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

    def _open_impact_in_browser(self) -> None:
        try:
            graph_svc = get_graph_service()
            analytics_svc = get_analytics_service()

            data = json.dumps(
                {
                    "edits": graph_svc.queries.recent_edits_with_symbols(limit=20),
                    "hotspots": [
                        {"path": h.path, "session_count": h.session_count}
                        for h in analytics_svc.queries.hotspot_files_global(limit=15)
                    ],
                    "patterns": [
                        {"first": p.first, "then": p.then, "frequency": p.frequency}
                        for p in graph_svc.queries.workflow_patterns_all(limit=15)
                    ],
                    "graph": graph_svc.queries.force_graph_data(limit=300),
                }
            )

            html_path = os.path.join(_ASSETS_DIR, "index.html")
            d3_path = os.path.join(_ASSETS_DIR, "d3.v7.min.js")
            with open(html_path) as f:
                html = f.read()
            with open(d3_path) as f:
                d3_js = f.read()

            html = html.replace('<script src="d3.v7.min.js"></script>', f"<script>{d3_js}</script>")
            html = html.replace("__DATA__", data)

            with tempfile.NamedTemporaryFile(suffix=".html", prefix="claudewatch-impact-", delete=False) as tmp:
                tmp.write(html.encode())
            webbrowser.open(f"file://{tmp.name}")
        except Exception:
            log.exception("failed to open impact graph in browser")

    def _bootstrap(self) -> None:
        try:
            get_graph_service().full_pipeline()
        except Exception:
            log.exception("graph bootstrap failed")
        finally:
            GraphPane._bootstrap_running = False


def _section_header(text: str) -> NSView:
    return label(text, size=10.0, color=theme.tertiary)


def _shorten_path(path: str, max_len: int = 40) -> str:
    if len(path) <= max_len:
        return path
    parts = path.split("/")
    if len(parts) > 2:
        return ".../" + "/".join(parts[-2:])
    return "..." + path[-(max_len - 3) :]


def _build_rows_card(card_w: float, rows: list[tuple[str, str]]) -> NSView:
    card_h = _CARD_PAD + len(rows) * _ROW_H + _CARD_PAD
    rows_card = card(card_w, card_h)
    content = rows_card.contentView()
    ry = card_h - _CARD_PAD
    for left_text, right_text in rows:
        ry -= _ROW_H
        left_label = label(left_text, size=12.0, color=theme.secondary)
        left_label.setFrame_(NSMakeRect(_CARD_PAD, ry, card_w - _CARD_PAD - 120, 18))
        content.addSubview_(left_label)
        right_label = label(right_text, size=12.0, bold=True)
        right_label.setFrame_(NSMakeRect(card_w - _CARD_PAD - 100, ry, 100, 18))
        content.addSubview_(right_label)
    return rows_card


def _build_edits_card(card_w: float, edits: list[dict[str, str]]) -> NSView:
    card_h = _CARD_PAD + len(edits) * _ROW_H + _CARD_PAD
    edits_card = card(card_w, card_h)
    content = edits_card.contentView()
    ry = card_h - _CARD_PAD
    for edit in edits:
        ry -= _ROW_H
        fn_name = edit.get("function", "?")
        file_short = _shorten_path(edit.get("file_path", ""), 25)
        left_label = label(f"{fn_name}  {file_short}", size=11.0)
        left_label.setFrame_(NSMakeRect(_CARD_PAD, ry, card_w - _CARD_PAD - 90, 18))
        content.addSubview_(left_label)
        ts = edit.get("timestamp", "")[:10]
        ts_label = label(ts, size=10.0, color=theme.tertiary)
        ts_label.setFrame_(NSMakeRect(card_w - _CARD_PAD - 80, ry, 80, 18))
        content.addSubview_(ts_label)
    return edits_card
