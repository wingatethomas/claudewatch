"""Stack-based layout — eliminates manual pixel math.

NSView uses bottom-up coordinates (y=0 is the bottom). VStack lets you
think top-down: add items sequentially, it handles the coordinate math.
"""

from __future__ import annotations

from AppKit import NSBox, NSScrollView, NSView
from Foundation import NSMakeRect


class VStack:
    """Vertical stack layout — items placed top-to-bottom.

    Usage::

        stack = VStack(width=490, padding=24, spacing=8)
        stack.add(pane_title("Settings"), height=24)
        stack.gap(8)
        stack.add(card_view, height=120)
        return stack.to_scroll_view(max_height=620)
    """

    def __init__(self, width: float, padding: float = 0, spacing: float = 0) -> None:
        self._width = width
        self._padding = padding
        self._spacing = spacing
        self._items: list[tuple[NSView, float]] = []  # (view, height)
        self._gaps: list[float] = []  # gap after each item (before next)
        self._total_content = 0.0  # sum of item heights + gaps (no padding)

    def add(self, view: NSView, height: float) -> VStack:
        """Add a view to the stack."""
        if self._items:
            # Add default spacing after previous item
            self._gaps[-1] += self._spacing
            self._total_content += self._spacing
        self._items.append((view, height))
        self._gaps.append(0)  # no gap after this item yet
        self._total_content += height
        return self

    def gap(self, points: float) -> VStack:
        """Add explicit vertical space after the last item."""
        if self._gaps:
            self._gaps[-1] += points
            self._total_content += points
        return self

    def separator(self) -> VStack:
        """Add a 1px horizontal separator line."""
        sep = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
        sep.setBoxType_(2)  # NSBoxSeparator
        return self.add(sep, height=1)

    @property
    def content_height(self) -> float:
        """Total height including padding."""
        return self._padding + self._total_content + self._padding

    def to_view(self) -> NSView:
        """Create an NSView with all items laid out top-to-bottom."""
        h = self.content_height
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self._width, h))
        content_w = self._width - self._padding * 2

        y = h - self._padding  # start at top

        for i, (view, item_h) in enumerate(self._items):
            y -= item_h
            # Set frame: x = padding, width = content width (if view has no width set)
            view_w = view.frame().size.width
            if view_w == 0:
                view_w = content_w
            view.setFrame_(NSMakeRect(self._padding, y, view_w, item_h))
            container.addSubview_(view)
            # Apply gap after this item
            if i < len(self._gaps):
                y -= self._gaps[i]

        return container

    def to_scroll_view(self, max_height: float) -> NSView:
        """Wrap in a scroll view if content exceeds max_height."""
        inner = self.to_view()
        if self.content_height <= max_height:
            inner.setFrame_(NSMakeRect(0, 0, self._width, max_height))
            return inner

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, self._width, max_height))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        scroll.setDocumentView_(inner)
        return scroll
