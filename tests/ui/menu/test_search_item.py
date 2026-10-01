"""Tests for the session search menu item builder and debounce scheduling."""

from unittest.mock import MagicMock

from AppKit import NSMenuItem, NSSearchField, NSViewWidthSizable
from Foundation import NSTimer

from claudewatch.ui.menu.core import AppDelegate
from claudewatch.ui.menu.search_item import build_search_item, schedule_search_debounce


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

    def test_field_delegate_wired_for_keystrokes(self) -> None:
        delegate = _make_delegate()
        _, search_field = build_search_item(delegate)
        assert search_field.delegate() is delegate

    def test_placeholder_set(self) -> None:
        _, search_field = build_search_item(_make_delegate())
        assert str(search_field.placeholderString())

    def test_container_and_field_stretch_to_menu_width(self) -> None:
        item, search_field = build_search_item(_make_delegate())
        assert item.view().autoresizingMask() & NSViewWidthSizable
        assert search_field.autoresizingMask() & NSViewWidthSizable


class TestScheduleSearchDebounce:
    def test_returns_timer_carrying_query(self) -> None:
        timer = schedule_search_debounce(_make_delegate(), "parser")
        assert isinstance(timer, NSTimer)
        assert str(timer.userInfo()) == "parser"
        timer.invalidate()

    def test_fire_dispatches_to_app(self) -> None:
        delegate = _make_delegate()
        app = MagicMock()
        delegate._app = app
        fired_queries: list[str] = []
        app.on_search_debounce.side_effect = lambda timer: fired_queries.append(str(timer.userInfo()))
        timer = schedule_search_debounce(delegate, "parser")
        timer.fire()
        assert fired_queries == ["parser"]

    def test_invalidated_timer_does_not_dispatch(self) -> None:
        delegate = _make_delegate()
        app = MagicMock()
        delegate._app = app
        timer = schedule_search_debounce(delegate, "parser")
        timer.invalidate()
        timer.fire()
        app.on_search_debounce.assert_not_called()
