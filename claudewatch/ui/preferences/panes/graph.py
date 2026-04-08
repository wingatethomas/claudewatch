"""Graph pane — human-readable change impact with tabs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import objc
from AppKit import (
    NSFont,
    NSScrollView,
    NSSegmentedControl,
    NSSegmentStyleTexturedRounded,
    NSView,
)
from Foundation import NSMakeRect

from claudewatch.backend.analytics.dependencies import get_analytics_service
from claudewatch.backend.core import features
from claudewatch.backend.graph.dependencies import get_graph_service
from claudewatch.ui.components.layout import VStack
from claudewatch.ui.components.tokens import Font
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane
from claudewatch.ui.theme import theme

log = logging.getLogger("claudewatch")


class GraphPane(BasePane):
    """Graph pane with tabs: Recent Changes, Impact, Hotspots."""

    @property
    def title(self) -> str:
        return "Graph"

    @property
    def subtitle(self) -> str:
        return "Change impact analysis"

    def build_content(self, view: NSView, content_top: float) -> None:
        graph_svc = get_graph_service()
        overview = graph_svc.queries.project_graph_all()

        if overview.sessions == 0:
            empty = secondary_label("No data yet. Graph populates after the first background scan.", size=13.0)
            empty.setFrame_(NSMakeRect(CONTENT_PADDING, content_top - 30, self.card_width, 18))
            view.addSubview_(empty)
            return

        # Tab control
        tab_y = content_top - 28
        tab_control = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            ["Recent Changes", "Impact", "Hotspots"],
            0,
            self.delegate,
            objc.selector(self.delegate.graphTabChanged_, signature=b"v@:@"),
        )
        tab_control.setFrame_(NSMakeRect(CONTENT_PADDING, tab_y, self.card_width, 24))
        tab_control.setSegmentStyle_(NSSegmentStyleTexturedRounded)
        tab_control.setFont_(NSFont.systemFontOfSize_(Font.SMALL))
        tab_idx = getattr(self.delegate, "_graph_tab", 0)
        tab_control.setSelectedSegment_(tab_idx)
        view.addSubview_(tab_control)

        # Content area below tabs
        content_top_after_tabs = tab_y - 8
        if tab_idx == 0:
            self._build_recent_changes(view, content_top_after_tabs)
        elif tab_idx == 1:
            self._build_impact(view, content_top_after_tabs)
        else:
            self._build_hotspots(view, content_top_after_tabs)

    def _build_recent_changes(self, view: NSView, content_top: float) -> None:
        """What did Claude change?"""
        graph_svc = get_graph_service()
        indexing_on = features.is_enabled("code_indexing")

        stack = VStack(width=self.card_width, padding=0, spacing=4)

        if indexing_on:
            edits = graph_svc.queries.recent_edits_with_symbols(limit=30)
            if edits:
                for edit in edits:
                    fn = edit.get("function", "")
                    fpath = edit.get("file_path", "")
                    ts = edit.get("timestamp", "")
                    display, full = _short_path(fpath)
                    time_ago = _relative_time(ts)

                    line = f"{fn}()  in {display}" if fn else display
                    row = _text_row(self.card_width, line, time_ago, tooltip=full)
                    stack.add(row, height=20)
            else:
                stack.add(
                    secondary_label("No edits with function data yet. Waiting for code indexing.", size=12.0), height=18
                )
        else:
            # Fall back to file-level edits from analytics
            analytics_svc = get_analytics_service()
            recent = analytics_svc.queries.recent_sessions(limit=5)
            if recent:
                for session in recent:
                    session_files = analytics_svc.queries.files_for_session(session.session_id)
                    edit_files = [f for f in session_files if f.count > 0][:5]
                    if edit_files:
                        project_label = label(
                            f"{session.proj_key}  {_relative_time(session.last_ts)}",
                            size=11.0,
                            color=theme.tertiary,
                        )
                        stack.add(project_label, height=16)
                        for file_entry in edit_files:
                            display, full = _short_path(file_entry.path)
                            row = _text_row(self.card_width, f"  {display}", f"{file_entry.count}x", tooltip=full)
                            stack.add(row, height=18)
                        stack.gap(4)
            else:
                stack.add(secondary_label("No recent sessions.", size=12.0), height=18)

            stack.gap(8)
            stack.add(
                secondary_label("Enable Code Indexing in Settings for function-level detail.", size=11.0), height=16
            )

        _place_stack(view, stack, self.card_width, content_top)

    def _build_impact(self, view: NSView, content_top: float) -> None:
        """What depends on what I changed?"""
        stack = VStack(width=self.card_width, padding=0, spacing=4)

        indexing_on = features.is_enabled("code_indexing")
        if not indexing_on:
            stack.add(secondary_label("Enable Code Indexing in Settings to see impact analysis.", size=12.0), height=18)
            _place_stack(view, stack, self.card_width, content_top)
            return

        graph_svc = get_graph_service()
        overview = graph_svc.queries.project_graph_all()
        if overview.symbols == 0:
            stack.add(secondary_label("Waiting for code indexing to complete...", size=12.0), height=18)
            _place_stack(view, stack, self.card_width, content_top)
            return

        edits = graph_svc.queries.recent_edits_with_symbols(limit=10)
        if not edits:
            stack.add(secondary_label("No recent edits with function data.", size=12.0), height=18)
            _place_stack(view, stack, self.card_width, content_top)
            return

        seen_actions: set[str] = set()
        for edit in edits:
            action_id = edit.get("session_id", "") + ":" + edit.get("function", "")
            if action_id in seen_actions:
                continue
            seen_actions.add(action_id)

            fn = edit.get("function", "?")
            impact = graph_svc.queries.cascading_impact(edit.get("session_id", ""))
            callers = impact.impacted[:5] if impact.impacted else []

            fn_label = label(f"{fn}()", size=12.0, bold=True)
            stack.add(fn_label, height=20)

            if callers:
                caller_names = ", ".join(c.rsplit(":", 1)[-1] + "()" for c in callers)
                caller_label = label(f"  called by {caller_names}", size=11.0, color=theme.secondary)
                stack.add(caller_label, height=18)
            else:
                no_callers = label("  no known callers", size=11.0, color=theme.tertiary)
                stack.add(no_callers, height=18)

            stack.gap(4)

        _place_stack(view, stack, self.card_width, content_top)

    def _build_hotspots(self, view: NSView, content_top: float) -> None:
        """What files keep getting changed?"""
        analytics_svc = get_analytics_service()
        hotspots = analytics_svc.queries.hotspot_files_global(min_sessions=2, limit=20)

        stack = VStack(width=self.card_width, padding=0, spacing=2)

        if not hotspots:
            stack.add(secondary_label("No file hotspots yet.", size=12.0), height=18)
        else:
            for hotspot in hotspots:
                display, full = _short_path(hotspot.path)
                row = _text_row(self.card_width, display, f"{hotspot.session_count} sessions", tooltip=full)
                stack.add(row, height=20)

        _place_stack(view, stack, self.card_width, content_top)


def _short_path(path: str) -> tuple[str, str]:
    """Return (display_text, full_path). Display shows last 3 path components."""
    parts = path.rstrip("/").split("/")
    if len(parts) >= 3:
        return "/".join(parts[-3:]), path
    if len(parts) >= 2:
        return "/".join(parts[-2:]), path
    return (parts[-1] if parts else path), path


def _text_row(width: float, left_text: str, right_text: str, tooltip: str = "") -> NSView:
    """A simple left-aligned + right-aligned text row with optional hover tooltip."""
    row = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, 20))
    left = label(left_text, size=12.0)
    left.setFrame_(NSMakeRect(0, 0, width - 100, 18))
    if tooltip:
        left.setToolTip_(tooltip)
    row.addSubview_(left)
    right = label(right_text, size=11.0, color=theme.tertiary)
    right.setFrame_(NSMakeRect(width - 96, 0, 96, 18))
    row.addSubview_(right)
    return row


def _place_stack(view: NSView, stack: VStack, card_width: float, content_top: float) -> None:
    """Place a VStack into the view, scrolling if needed."""
    scroll_h = content_top
    if stack.content_height <= scroll_h:
        content_view = stack.to_view(min_height=scroll_h)
        content_view.setFrame_(NSMakeRect(CONTENT_PADDING, 0, card_width, scroll_h))
        view.addSubview_(content_view)
    else:
        inner = stack.to_view()
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(CONTENT_PADDING, 0, card_width, scroll_h))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        scroll.setDocumentView_(inner)
        inner.scrollPoint_((0, inner.frame().size.height))
        view.addSubview_(scroll)


def _relative_time(ts: str) -> str:  # noqa: PLR0911
    """Convert ISO timestamp to human-readable relative time."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta = datetime.now(tz=UTC) - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            mins = seconds // 60
            return f"{mins}m ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours}h ago"
        days = seconds // 86400
        if days == 1:
            return "yesterday"
        if days < 30:
            return f"{days}d ago"
        return ts[:10]
    except (ValueError, TypeError):
        return ts[:10] if len(ts) >= 10 else ""
