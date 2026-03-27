"""Tests for VStack layout system."""

from AppKit import NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.layout import VStack


class TestVStack:
    def test_empty_stack_has_padding_height(self) -> None:
        stack = VStack(width=400, padding=20)
        view = stack.to_view()
        assert view.frame().size.height == 40

    def test_single_item_positioned_at_top(self) -> None:
        stack = VStack(width=400, padding=20)
        child = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 30))
        stack.add(child, height=30)
        view = stack.to_view()
        child_frame = child.frame()
        expected_y = view.frame().size.height - 20 - 30
        assert child_frame.origin.y == expected_y

    def test_two_items_stacked_vertically(self) -> None:
        stack = VStack(width=400, padding=10, spacing=8)
        child1 = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        child2 = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 30))
        stack.add(child1, height=20)
        stack.add(child2, height=30)
        stack.to_view()
        assert child1.frame().origin.y > child2.frame().origin.y

    def test_gap_adds_space(self) -> None:
        stack = VStack(width=400, padding=0, spacing=0)
        child1 = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        child2 = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        stack.add(child1, height=20)
        stack.gap(50)
        stack.add(child2, height=20)
        stack.to_view()
        gap = child1.frame().origin.y - child2.frame().origin.y - 20
        assert gap == 50

    def test_width_propagated_to_children(self) -> None:
        stack = VStack(width=400, padding=20)
        child = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 30))
        stack.add(child, height=30)
        stack.to_view()
        assert child.frame().size.width == 360

    def test_separator_adds_1px(self) -> None:
        stack = VStack(width=400, padding=0, spacing=0)
        child1 = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        child2 = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        stack.add(child1, height=20)
        stack.separator()
        stack.add(child2, height=20)
        view = stack.to_view()
        assert view.frame().size.height == 41

    def test_content_height_property(self) -> None:
        stack = VStack(width=400, padding=10, spacing=5)
        child = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 30))
        stack.add(child, height=30)
        assert stack.content_height == 50

    def test_to_scroll_view_wraps_when_exceeds_height(self) -> None:
        stack = VStack(width=400, padding=0, spacing=0)
        for _ in range(20):
            child = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 50))
            stack.add(child, height=50)
        scroll = stack.to_scroll_view(max_height=200)
        assert scroll.frame().size.height == 200

    def test_to_scroll_view_no_scroll_when_fits(self) -> None:
        stack = VStack(width=400, padding=0, spacing=0)
        child = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 50))
        stack.add(child, height=50)
        view = stack.to_scroll_view(max_height=200)
        assert view.frame().size.height == 200

    def test_children_added_as_subviews(self) -> None:
        stack = VStack(width=400, padding=0)
        child1 = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        child2 = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        stack.add(child1, height=20)
        stack.add(child2, height=20)
        view = stack.to_view()
        subviews = list(view.subviews())
        assert child1 in subviews
        assert child2 in subviews
