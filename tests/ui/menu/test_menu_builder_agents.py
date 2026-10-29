"""Tests for nested agent-team rows in the menu."""

from unittest.mock import MagicMock, patch

from AppKit import NSMenu

from claudewatch.backend.core.dto import TokenUsageDTO
from claudewatch.backend.core.models import ClaudeSession, HostApp, SessionStatus
from claudewatch.ui.menu.core import AppDelegate
from claudewatch.ui.menu_builder import MenuBuilder

_TASK = "ORM authorization variant conditions"


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
    app._summary_service.get_cached_summary.return_value = None
    app._summary_service.get_cached.return_value = None
    app._bookmark_service.is_bookmarked.return_value = False
    app._bookmark_service.get_all.return_value = []
    app._history_service.get_all.return_value = []
    app._analytics_service.agents_for_session.return_value = []
    app._usage_service.get_tokens.return_value = TokenUsageDTO(input=0, output=0, cache_create=0, cache_read=0)
    app._usage_service.get_model.return_value = ""
    return app


def _parent(pid: int = 1) -> ClaudeSession:
    return ClaudeSession(
        pid=pid,
        tty="ttys001",
        project="mainproj",
        cwd="/tmp/mainproj",
        host_app=HostApp.TERMINAL,
        status=SessionStatus.WORKING,
        ai_title=_TASK,
        session_id="s1",
    )


def _agent(pid: int = 9, parent_pid: int = 1) -> ClaudeSession:
    return ClaudeSession(
        pid=pid,
        tty="ttys009",
        project="otherrepo",
        cwd="/tmp/otherrepo",
        host_app=HostApp.TERMINAL,
        status=SessionStatus.WORKING,
        window_title=f"otherrepo — ⠋ {_TASK} — node ◂ claude",
        agent_of_pid=parent_pid,
    )


def _build(sessions: list[ClaudeSession]) -> tuple[MenuBuilder, NSMenu, MagicMock]:
    app = _make_app()
    menu = NSMenu.alloc().init()
    builder = MenuBuilder(app, menu, AppDelegate.alloc().init())
    with patch("claudewatch.ui.menu_builder.features.is_enabled", return_value=False):
        builder.build(sessions)
    return builder, menu, app


class TestNestedAgentRows:
    def test_agent_not_a_top_level_row(self) -> None:
        builder, menu, _ = _build([_parent(), _agent()])
        assert len(builder._sections) == 1
        assert len(builder._sections[0].rows) == 1
        titles = [str(item.title()) for item in menu.itemArray()]
        assert not any(t.startswith("✦ otherrepo") for t in titles)

    def test_agent_row_rendered_after_parent(self) -> None:
        _, menu, _ = _build([_parent(), _agent()])
        titles = [str(item.title()) for item in menu.itemArray()]
        parent_index = next(i for i, t in enumerate(titles) if "mainproj" in t)
        agent_index = next(i for i, t in enumerate(titles) if "⤷ otherrepo" in t)
        assert agent_index > parent_index

    def test_agent_in_parent_extra_items_and_filters_with_parent(self) -> None:
        builder, _, _ = _build([_parent(), _agent()])
        row = builder._sections[0].rows[0]
        assert len(row.extra_items) == 1
        builder.set_query("zzz-no-match")
        assert row.item.isHidden()
        assert row.extra_items[0].isHidden()
        builder.set_query("otherrepo")
        assert not row.item.isHidden()
        assert not row.extra_items[0].isHidden()

    def test_section_count_excludes_agents(self) -> None:
        builder, _, _ = _build([_parent(), _agent()])
        header_title = str(builder._sections[0].header.attributedTitle().string())
        assert "(1)" in header_title

    def test_status_icon_excludes_agents(self) -> None:
        with patch("claudewatch.ui.menu_builder.render_status_icon") as icon_mock:
            _build([_parent(), _agent()])
        attention, working, idle = icon_mock.call_args.args
        assert [s.pid for s in working] == [1]
        assert attention == []
        assert idle == []

    def test_suffix_map_ignores_agents(self) -> None:
        agent = _agent()
        agent.ai_title = _TASK
        agent.project = "mainproj"
        _, menu, _ = _build([_parent(), agent])
        titles = [str(item.title()) for item in menu.itemArray()]
        assert not any("#1" in t for t in titles)

    def test_agent_item_clickable_and_styled(self) -> None:
        builder, _, _ = _build([_parent(), _agent()])
        agent_item = builder._sections[0].rows[0].extra_items[0]
        assert agent_item.tag() > 0
        assert agent_item.attributedTitle() is not None
        assert "⤷ otherrepo — working" in str(agent_item.title())

    def test_agents_only_list_shows_placeholder(self) -> None:
        _, menu, _ = _build([_agent()])
        titles = [str(item.title()) for item in menu.itemArray()]
        assert any("No running Claude sessions" in t for t in titles)
