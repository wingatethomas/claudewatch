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
