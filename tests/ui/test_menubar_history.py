"""Tests for ended-session history recording in ClaudeWatchApp._log_changes."""

from unittest.mock import MagicMock

from claudewatch.backend.core.models import ClaudeSession, HostApp
from claudewatch.ui.menubar import ClaudeWatchApp


def _session(pid: int, project: str, *, agent_of: int | None = None, session_id: str = "") -> ClaudeSession:
    return ClaudeSession(
        pid=pid,
        tty=f"ttys{pid:03d}",
        project=project,
        cwd=f"/tmp/{project}",
        host_app=HostApp.TERMINAL,
        session_id=session_id,
        agent_of_pid=agent_of,
    )


def _make_app(prev_sessions: dict[int, ClaudeSession]) -> MagicMock:
    app = MagicMock()
    app.sessions = []
    app._prev_pids = set(prev_sessions)
    app._prev_status = {}
    app._prev_sessions = prev_sessions
    app._onboarding_service.is_tip_shown.return_value = True
    app._usage_service.get_model.return_value = ""
    return app


class TestHistoryRecording:
    def test_ended_agent_not_recorded(self) -> None:
        app = _make_app(
            {
                1: _session(1, "mainproj", session_id="s1"),
                9: _session(9, "otherrepo", agent_of=1),
            }
        )
        ClaudeWatchApp._log_changes(app)
        assert app._history_service.record.call_count == 1
        assert app._history_service.record.call_args.kwargs["project"] == "mainproj"

    def test_ended_principal_recorded(self) -> None:
        app = _make_app({1: _session(1, "mainproj", session_id="s1")})
        ClaudeWatchApp._log_changes(app)
        app._history_service.record.assert_called_once()


class TestHistoryPermissionMode:
    def test_ended_session_records_permission_mode(self) -> None:
        session = _session(1, "mainproj", session_id="s1")
        session.permission_mode = "auto"
        app = _make_app({1: session})
        ClaudeWatchApp._log_changes(app)
        assert app._history_service.record.call_args.kwargs["permission_mode"] == "auto"


class TestMenuKeyEndedSet:
    def _key(self, ended_sids: list[str]) -> str:
        from claudewatch.backend.core.dto import HistoryEntryDTO

        app = MagicMock()
        app.sessions = []
        app._summary_service.get_cached.return_value = ""
        app._recently_finished = [
            HistoryEntryDTO(
                session_id=sid,
                project="p",
                cwd="/tmp/p",
                model="",
                host_app="Terminal",
                ended_at="2026-11-06T12:00:00+00:00",
                permission_mode="auto",
            )
            for sid in ended_sids
        ]
        return ClaudeWatchApp._menu_key(app)

    def test_key_changes_with_ended_set(self) -> None:
        assert self._key(["a"]) != self._key(["a", "b"])
        assert self._key(["a"]) == self._key(["a"])


class TestEndedAtFromLastActivity:
    def test_ended_at_uses_last_activity_when_known(self) -> None:
        session = _session(1, "mainproj", session_id="s1")
        session.last_activity = 1_700_000_000.0
        app = _make_app({1: session})
        ClaudeWatchApp._log_changes(app)
        ended_at = app._history_service.record.call_args.kwargs["ended_at"]
        assert ended_at.startswith("2023-11-14")

    def test_ended_at_empty_when_activity_unknown(self) -> None:
        session = _session(1, "mainproj", session_id="s1")
        app = _make_app({1: session})
        ClaudeWatchApp._log_changes(app)
        assert app._history_service.record.call_args.kwargs["ended_at"] == ""


class TestUserQuitSuppression:
    def test_user_quit_session_not_marked_auto(self) -> None:
        session = _session(1, "mainproj", session_id="s1")
        session.permission_mode = "auto"
        session.last_activity = 1_700_000_000.0
        app = _make_app({1: session})
        app._exiting_pids = {1: 123.0}
        ClaudeWatchApp._log_changes(app)
        assert app._history_service.record.call_args.kwargs["permission_mode"] == ""

    def test_natural_exit_keeps_permission_mode(self) -> None:
        session = _session(1, "mainproj", session_id="s1")
        session.permission_mode = "auto"
        app = _make_app({1: session})
        app._exiting_pids = {}
        ClaudeWatchApp._log_changes(app)
        assert app._history_service.record.call_args.kwargs["permission_mode"] == "auto"
