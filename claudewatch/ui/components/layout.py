"""Stack-based layout — eliminates manual pixel math.

NSView uses bottom-up coordinates (y=0 is the bottom). VStack lets you
think top-down: add items sequentially, it handles the coordinate math.

Design system layout rules
--------------------------
1. **Zero-frame convention**: All widgets (labels, buttons) MUST start with
   frame (0, 0, 0, 0). The layout system or caller sets the actual frame.
   This prevents intrinsic sizing from fighting the layout.

2. **VStack owns width**: When a view is added to VStack, VStack sets its
   width to ``container_width - 2 * padding``. Don't pre-set width on views
   managed by VStack.

3. **Cards own their internals**: Cards position their own child views using
   manual coordinates inside ``contentView()``. VStack only positions the
   card itself.

4. **No manual pixel math outside cards**: Everything between pane header
   and pane bottom should go through VStack. Manual y-tracking is only
   allowed inside card content views.
"""

from __future__ import annotations

from AppKit import NSBox, NSScrollView, NSView
from Foundation import NSMakeRect


class VStack:
    """Vertical stack layout — items placed top-to-bottom."""

    def __init__(self, width: float, padding: float = 0, spacing: float = 0) -> None:
        self._width = width
        self._padding = padding
        self._spacing = spacing
        self._items: list[tuple[NSView, float]] = []
        self._gaps: list[float] = []
        self._total_content = 0.0

    def add(self, view: NSView, height: float) -> VStack:
        """Add a view to the stack."""
        if self._items:
            self._gaps[-1] += self._spacing
            self._total_content += self._spacing
        self._items.append((view, height))
        self._gaps.append(0)
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
        sep.setBoxType_(2)
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
        y = h - self._padding
        for i, (view, item_h) in enumerate(self._items):
            y -= item_h
            view_w = view.frame().size.width
            if view_w == 0:
                view_w = content_w
            view.setFrame_(NSMakeRect(self._padding, y, view_w, item_h))
            container.addSubview_(view)
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
