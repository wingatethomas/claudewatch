"""Tests for session submenu builder."""

from unittest.mock import MagicMock

from AppKit import NSMenu

from claudewatch.ui.menu.session_submenu import SessionActions, build_session_submenu


def _menu_titles(menu: NSMenu) -> list[str]:
    """Extract all item titles from a menu (excluding separators)."""
    return [str(item.title()) for item in menu.itemArray() if not item.isSeparatorItem()]


class TestSessionSubmenu:
    def _make_delegate(self) -> MagicMock:
        d = MagicMock()
        d._callbacks = {}
        d._next_tag = 1
        return d

    def test_returns_menu(self) -> None:
        sub = build_session_submenu(delegate=self._make_delegate(), summary=None)
        assert isinstance(sub, NSMenu)

    def test_has_summary_item(self) -> None:
        sub = build_session_submenu(delegate=self._make_delegate(), summary="Fixed the bug")
        titles = _menu_titles(sub)
        assert "Summary" in titles

    def test_generating_state(self) -> None:
        sub = build_session_submenu(delegate=self._make_delegate(), summary=None, generating=True)
        summary_item = sub.itemArray()[0]
        sub_titles = _menu_titles(summary_item.submenu())
        assert any("Generating" in t for t in sub_titles)

    def test_has_usage_item(self) -> None:
        act = SessionActions(usage_lines=["Input: 100 tokens"])
        sub = build_session_submenu(delegate=self._make_delegate(), summary=None, actions=act)
        titles = _menu_titles(sub)
        assert "Usage" in titles

    def test_resume_handler(self) -> None:
        act = SessionActions(resume=lambda _: None)
        sub = build_session_submenu(delegate=self._make_delegate(), summary=None, actions=act)
        titles = _menu_titles(sub)
        assert "Resume" in titles

    def test_bookmark_handler(self) -> None:
        act = SessionActions(bookmark=lambda _: None)
        sub = build_session_submenu(delegate=self._make_delegate(), summary=None, actions=act)
        titles = _menu_titles(sub)
        assert "Bookmark..." in titles

    def test_quit_handler(self) -> None:
        act = SessionActions(quit=lambda _: None)
        sub = build_session_submenu(delegate=self._make_delegate(), summary=None, actions=act)
        titles = _menu_titles(sub)
        assert "Quit session" in titles

    def test_no_optional_actions(self) -> None:
        sub = build_session_submenu(delegate=self._make_delegate(), summary=None)
        titles = _menu_titles(sub)
        assert "Resume" not in titles
        assert "Bookmark..." not in titles
        assert "Quit session" not in titles

    def test_remove_handler(self) -> None:
        act = SessionActions(remove=lambda _: None)
        sub = build_session_submenu(delegate=self._make_delegate(), summary=None, actions=act)
        titles = _menu_titles(sub)
        assert "Remove" in titles
