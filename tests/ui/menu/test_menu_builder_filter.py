"""Integration tests for MenuBuilder's session search filter."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from AppKit import NSMenu

from claudewatch.backend.core.dto import HistoryEntryDTO, TokenUsageDTO
from claudewatch.backend.core.models import ClaudeSession, HostApp, SessionStatus
from claudewatch.ui.menu.core import AppDelegate
from claudewatch.ui.menu_builder import MenuBuilder

_SUMMARIES = {
    "/tmp/alpha": "rewrote the tokenizer",
    "/tmp/beta": None,
    "/tmp/gamma": "built the gamma dashboard",
}


def _make_history_entry(project: str = "gamma", cwd: str = "/tmp/gamma") -> HistoryEntryDTO:
    return HistoryEntryDTO(
        session_id="s9",
        project=project,
        cwd=cwd,
        model="",
        host_app="Terminal",
        ended_at=datetime.now(tz=UTC).isoformat(),
    )


def _make_app() -> MagicMock:
    app = MagicMock()
    app._menu_open = False
    app._last_menu_key = ""
    app._menu_key.return_value = "key-1"
    app._has_polled = True
    app._accessibility_warning = False
    app._status_item = None
    app._update_service.get_cached.return_value = None
    app._onboarding_service.is_tip_shown.return_value = True
    app._summary_service.get_cached_summary.side_effect = lambda cwd, session_id="": _SUMMARIES.get(cwd)
    app._bookmark_service.is_bookmarked.return_value = False
    app._bookmark_service.get_all.return_value = []
    app._history_service.get_all.return_value = []
    app._analytics_service.agents_for_session.return_value = []
    app._usage_service.get_tokens.return_value = TokenUsageDTO(input=0, output=0, cache_create=0, cache_read=0)
    app._usage_service.get_model.return_value = ""
    return app


def _make_sessions() -> list[ClaudeSession]:
    return [
        ClaudeSession(
            pid=1,
            tty="ttys001",
            project="alpha",
            cwd="/tmp/alpha",
            host_app=HostApp.TERMINAL,
            status=SessionStatus.WORKING,
            ai_title="fix the parser",
            session_id="s1",
        ),
        ClaudeSession(
            pid=2,
            tty="ttys002",
            project="beta",
            cwd="/tmp/beta",
            host_app=HostApp.TERMINAL,
            status=SessionStatus.IDLE,
            ai_title="write docs",
            session_id="s2",
        ),
    ]


def _make_builder() -> tuple[MenuBuilder, NSMenu, MagicMock]:
    app = _make_app()
    menu = NSMenu.alloc().init()
    delegate = AppDelegate.alloc().init()
    builder = MenuBuilder(app, menu, delegate)
    return builder, menu, app


class TestMenuBuilderFilter:
    def _build(self, builder: MenuBuilder, sessions: list[ClaudeSession]) -> None:
        with patch("claudewatch.ui.menu_builder.features.is_enabled", return_value=False):
            builder.build(sessions)

    def test_search_item_present_with_sessions(self) -> None:
        builder, menu, _ = _make_builder()
        self._build(builder, _make_sessions())
        assert builder._search_item in list(menu.itemArray())

    def test_search_item_absent_without_sessions(self) -> None:
        builder, menu, _ = _make_builder()
        self._build(builder, [])
        assert builder._search_item not in list(menu.itemArray())

    def test_sections_registered(self) -> None:
        builder, _, _ = _make_builder()
        self._build(builder, _make_sessions())
        assert len(builder._sections) == 2
        assert all(len(section.rows) == 1 for section in builder._sections)

    def test_set_query_filters_rows(self) -> None:
        builder, _, _ = _make_builder()
        self._build(builder, _make_sessions())
        builder.set_query("parser")
        working_section, idle_section = builder._sections
        assert not working_section.rows[0].item.isHidden()
        assert idle_section.rows[0].item.isHidden()
        assert idle_section.header.isHidden()

    def test_query_matches_cached_summary(self) -> None:
        builder, _, _ = _make_builder()
        self._build(builder, _make_sessions())
        builder.set_query("tokenizer")
        working_section, idle_section = builder._sections
        assert not working_section.rows[0].item.isHidden()
        assert idle_section.rows[0].item.isHidden()

    def test_no_match_item_shown_for_unmatched_query(self) -> None:
        builder, _, _ = _make_builder()
        self._build(builder, _make_sessions())
        builder.set_query("zzz-no-match")
        assert builder._no_match_item is not None
        assert not builder._no_match_item.isHidden()

    def test_clear_filter_restores(self) -> None:
        builder, _, _ = _make_builder()
        self._build(builder, _make_sessions())
        builder.set_query("zzz-no-match")
        builder.clear_filter()
        assert str(builder._search_field.stringValue()) == ""
        assert all(not row.item.isHidden() for section in builder._sections for row in section.rows)
        assert builder._no_match_item.isHidden()

    def test_rebuild_reapplies_filter(self) -> None:
        builder, _, app = _make_builder()
        self._build(builder, _make_sessions())
        builder.set_query("parser")
        app._menu_key.return_value = "key-2"
        self._build(builder, _make_sessions())
        working_section, idle_section = builder._sections
        assert not working_section.rows[0].item.isHidden()
        assert idle_section.rows[0].item.isHidden()

    def test_build_skipped_while_menu_open_with_active_filter(self) -> None:
        builder, menu, app = _make_builder()
        self._build(builder, _make_sessions())
        builder.set_query("parser")
        app._menu_open = True
        app._menu_key.return_value = "key-2"
        items_before = list(menu.itemArray())
        self._build(builder, _make_sessions())
        assert list(menu.itemArray()) == items_before

    def test_build_proceeds_while_menu_open_without_filter(self) -> None:
        builder, menu, app = _make_builder()
        self._build(builder, _make_sessions())
        app._menu_open = True
        app._menu_key.return_value = "key-2"
        first_item_before = menu.itemArray()[0]
        self._build(builder, _make_sessions())
        assert app._last_menu_key == "key-2"
        assert menu.itemArray()[0] is not None
        assert first_item_before is not None


class TestRecentsSection:
    def _build_with_recents(self) -> tuple[MenuBuilder, NSMenu, MagicMock]:
        builder, menu, app = _make_builder()
        app._history_service.get_all.return_value = [_make_history_entry()]
        with patch("claudewatch.ui.menu_builder.features.is_enabled", return_value=False):
            builder.build(_make_sessions())
        return builder, menu, app

    def _recents_section(self, builder: MenuBuilder):  # noqa: ANN202
        return builder._sections[-1]

    def test_recents_section_registered_and_hidden(self) -> None:
        builder, _, _ = self._build_with_recents()
        recents = self._recents_section(builder)
        assert recents.only_when_searching
        assert recents.header.isHidden()
        assert all(row.item.isHidden() for row in recents.rows)
        assert recents.leading_separator.isHidden()

    def test_search_reveals_matching_recent_by_project(self) -> None:
        builder, _, _ = self._build_with_recents()
        builder.set_query("gamma")
        recents = self._recents_section(builder)
        assert not recents.header.isHidden()
        assert not recents.rows[0].item.isHidden()

    def test_search_reveals_matching_recent_by_summary(self) -> None:
        builder, _, _ = self._build_with_recents()
        builder.set_query("dashboard")
        recents = self._recents_section(builder)
        assert not recents.rows[0].item.isHidden()

    def test_matching_recent_suppresses_no_match(self) -> None:
        builder, _, _ = self._build_with_recents()
        builder.set_query("gamma")
        assert builder._no_match_item.isHidden()

    def test_separator_shown_when_actives_also_match(self) -> None:
        builder, _, app = self._build_with_recents()
        app._history_service.get_all.return_value = [_make_history_entry(project="parser-archive")]
        app._menu_key.return_value = "key-2"
        with patch("claudewatch.ui.menu_builder.features.is_enabled", return_value=False):
            builder.build(_make_sessions())
        builder.set_query("parser")
        recents = self._recents_section(builder)
        assert not recents.rows[0].item.isHidden()
        assert not recents.leading_separator.isHidden()

    def test_clear_filter_hides_recents_again(self) -> None:
        builder, _, _ = self._build_with_recents()
        builder.set_query("gamma")
        builder.clear_filter()
        recents = self._recents_section(builder)
        assert recents.header.isHidden()
        assert all(row.item.isHidden() for row in recents.rows)

    def test_recent_submenu_item_still_present(self) -> None:
        _, menu, _ = self._build_with_recents()
        titles = [str(item.title()) for item in menu.itemArray()]
        assert "Recent (1)" in titles
