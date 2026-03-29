"""Tests for claudewatch.ui.focus — Accessibility guards on System Events calls."""

from unittest.mock import MagicMock, patch

from claudewatch.backend.core.models import ClaudeSession, HostApp, SessionStatus

_MOD = "claudewatch.ui.focus"


def _make_session(**kwargs: object) -> ClaudeSession:
    defaults = {
        "pid": 100,
        "tty": "ttys001",
        "project": "testproject",
        "cwd": "/tmp/testproject",
        "host_app": HostApp.TERMINAL,
        "status": SessionStatus.WORKING,
    }
    defaults.update(kwargs)
    return ClaudeSession(**defaults)


class TestFocusIdeTabAccessibilityGuard:
    """_focus_ide_tab returns early when Accessibility is not trusted."""

    def test_skips_applescript_when_not_trusted(self) -> None:
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=False),
            patch(f"{_MOD}.run_applescript") as mock_run,
        ):
            from claudewatch.ui.focus import _focus_ide_tab

            _focus_ide_tab("pycharm", "pycharm", "myproject", None)
        mock_run.assert_not_called()

    def test_runs_applescript_when_trusted(self) -> None:
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=True),
            patch(f"{_MOD}.run_applescript", return_value=""),
        ):
            from claudewatch.ui.focus import _focus_ide_tab

            _focus_ide_tab("pycharm", "pycharm", "myproject", None)
            # No exception means it proceeded past the guard


class TestFindJetbrainsProcessAccessibilityGuard:
    """_find_jetbrains_process returns default when Accessibility is not trusted."""

    def test_returns_pycharm_when_not_trusted(self) -> None:
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=False),
            patch(f"{_MOD}.run_applescript") as mock_run,
        ):
            from claudewatch.ui.focus import _find_jetbrains_process

            result = _find_jetbrains_process()
        assert result == "pycharm"
        mock_run.assert_not_called()

    def test_calls_applescript_when_trusted(self) -> None:
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=True),
            patch(f"{_MOD}.run_applescript", return_value="idea"),
        ):
            from claudewatch.ui.focus import _find_jetbrains_process

            result = _find_jetbrains_process()
        assert result == "idea"


class TestFocusSessionAccessibilityGuard:
    """focus_session for IDE hosts respects the Accessibility guard."""

    def test_pycharm_focus_skips_when_not_trusted(self) -> None:
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=False),
            patch(f"{_MOD}.run_applescript") as mock_run,
        ):
            from claudewatch.ui.focus import focus_session

            session = _make_session(host_app=HostApp.PYCHARM)
            focus_session(session)
        mock_run.assert_not_called()

    def test_vscode_focus_skips_when_not_trusted(self) -> None:
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=False),
            patch(f"{_MOD}.run_applescript") as mock_run,
        ):
            from claudewatch.ui.focus import focus_session

            session = _make_session(host_app=HostApp.VSCODE)
            focus_session(session)
        mock_run.assert_not_called()

    def test_terminal_focus_not_blocked_by_accessibility(self) -> None:
        """Terminal focus uses 'tell application Terminal', not System Events."""
        mock_ns = MagicMock()
        mock_ns.runningApplicationsWithBundleIdentifier_.return_value = [MagicMock()]
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=False),
            patch(f"{_MOD}.run_applescript") as mock_run,
            patch(f"{_MOD}.NSRunningApplication", mock_ns),
        ):
            from claudewatch.ui.focus import focus_session

            session = _make_session(host_app=HostApp.TERMINAL, window_id=12345)
            focus_session(session)
        # Terminal focus uses run_applescript for "tell application Terminal" — no AX guard
        mock_run.assert_called_once()
