"""Graph pane — interactive D3.js visualizations via WKWebView."""

from __future__ import annotations

import json
import logging
import os
import threading

from AppKit import NSView
from Foundation import NSURL, NSMakeRect
from WebKit import WKWebView, WKWebViewConfiguration

from claudewatch.backend.analytics.dependencies import get_analytics_service
from claudewatch.backend.graph.dependencies import get_graph_service
from claudewatch.ui.components.widgets.labels import secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane

log = logging.getLogger("claudewatch")

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "graph_assets")


class GraphPane(BasePane):
    """Graph pane with interactive D3.js visualizations."""

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

        analytics_svc = get_analytics_service()
        patterns = graph_svc.queries.workflow_patterns_all(limit=15)
        hotspots = analytics_svc.queries.hotspot_files_global(limit=15)
        graph_data = graph_svc.queries.force_graph_data(limit=300)

        data = json.dumps(
            {
                "overview": {
                    "sessions": overview.sessions,
                    "actions": overview.actions,
                    "files": overview.files,
                    "symbols": overview.symbols,
                },
                "patterns": [{"first": p.first, "then": p.then, "frequency": p.frequency} for p in patterns],
                "hotspots": [{"path": h.path, "session_count": h.session_count} for h in hotspots],
                "graph": graph_data,
            }
        )

        html_path = os.path.join(_ASSETS_DIR, "index.html")
        with open(html_path) as f:
            html = f.read()
        html = html.replace("__DATA__", data)

        content_w = self.width - 2 * CONTENT_PADDING
        config = WKWebViewConfiguration.alloc().init()
        web_view = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(CONTENT_PADDING, 0, content_w, content_top),
            config,
        )
        web_view.setOpaque_(False)
        web_view.setValue_forKey_(False, "drawsBackground")

        base_url = NSURL.fileURLWithPath_(_ASSETS_DIR + "/")
        web_view.loadHTMLString_baseURL_(html, base_url)
        view.addSubview_(web_view)

    def _bootstrap(self) -> None:
        try:
            get_graph_service().ingest_sessions()
        except Exception:
            log.exception("graph bootstrap failed")
        finally:
            GraphPane._bootstrap_running = False
