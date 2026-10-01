"""Tests for the session search menu item builder."""

from AppKit import NSMenuItem, NSSearchField

from claudewatch.ui.menu.core import AppDelegate
from claudewatch.ui.menu.search_item import build_search_item


def _make_delegate() -> AppDelegate:
    return AppDelegate.alloc().init()


class TestBuildSearchItem:
    def test_returns_item_and_field(self) -> None:
        item, search_field = build_search_item(_make_delegate())
        assert isinstance(item, NSMenuItem)
        assert isinstance(search_field, NSSearchField)

    def test_item_view_contains_field(self) -> None:
        item, search_field = build_search_item(_make_delegate())
        assert item.view() is not None
        assert search_field in list(item.view().subviews())

    def test_target_and_action_wired(self) -> None:
        delegate = _make_delegate()
        _, search_field = build_search_item(delegate)
        assert search_field.target() is delegate
        assert "sessionSearchChanged" in str(search_field.action())

    def test_placeholder_set(self) -> None:
        _, search_field = build_search_item(_make_delegate())
        assert str(search_field.placeholderString())

    def test_sends_search_string_immediately(self) -> None:
        _, search_field = build_search_item(_make_delegate())
        assert search_field.sendsSearchStringImmediately()
