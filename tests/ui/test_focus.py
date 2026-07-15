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

            _focus_ide_tab("pycharm", "myproject", None)
        mock_run.assert_not_called()

    def test_runs_applescript_when_trusted(self) -> None:
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=True),
            patch(f"{_MOD}.run_applescript", return_value=""),
        ):
            from claudewatch.ui.focus import _focus_ide_tab

            _focus_ide_tab("pycharm", "myproject", None)
            # No exception means it proceeded past the guard

    def test_activation_is_separate_from_window_raise(self) -> None:
        """Activation must run on its own — a failed window-name match (IDE
        diff viewers carry no project name) must not abort it."""
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=True),
            patch(f"{_MOD}.run_applescript", return_value="") as mock_run,
        ):
            from claudewatch.ui.focus import _focus_ide_tab

            _focus_ide_tab("pycharm", "myproject", None)
        scripts = [c.args[0] for c in mock_run.call_args_list]
        assert "frontmost" in scripts[0]
        assert "AXRaise" not in scripts[0]
        assert any("AXRaise" in s and "try" in s for s in scripts[1:])


class TestFocusIdeTabNoWindowSentinel:
    """Tab switching skips cleanly when no window title exposes the project."""

    def test_panel_check_sentinel_skips_tab_click_path(self) -> None:
        """JetBrains path: sentinel from the panel check stops before the
        panel toggle and the tab-position enumeration."""
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=True),
            patch(f"{_MOD}.run_applescript", side_effect=["", "", "no-window"]) as mock_run,
            patch(f"{_MOD}._click_at") as mock_click,
            patch(f"{_MOD}.time"),
        ):
            from claudewatch.ui.focus import _focus_ide_tab

            _focus_ide_tab("pycharm", "myproject", 0)
        assert mock_run.call_count == 3  # activate, raise, panel check — nothing after
        mock_click.assert_not_called()

    def test_enumeration_sentinel_skips_tab_click(self) -> None:
        """VS Code path (no panel check): sentinel from the tab-position
        enumeration skips the click."""
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=True),
            patch(f"{_MOD}.run_applescript", side_effect=["", "", "no-window"]) as mock_run,
            patch(f"{_MOD}._click_at") as mock_click,
            patch(f"{_MOD}.time"),
        ):
            from claudewatch.ui.focus import _focus_ide_tab

            _focus_ide_tab("Code", "myproject", 0)
        assert mock_run.call_count == 3  # activate, raise, tab enumeration
        mock_click.assert_not_called()

    def test_window_lookups_are_try_guarded_in_scripts(self) -> None:
        """Both tab-switching scripts guard the whose-clause with a try that
        returns the sentinel instead of throwing."""
        with (
            patch(f"{_MOD}.is_accessibility_trusted", return_value=True),
            patch(f"{_MOD}.run_applescript", return_value="") as mock_run,
            patch(f"{_MOD}._click_at"),
            patch(f"{_MOD}.time"),
        ):
            from claudewatch.ui.focus import _focus_ide_tab

            _focus_ide_tab("pycharm", "myproject", 0)
        scripts = [c.args[0] for c in mock_run.call_args_list]
        lookups = [s for s in scripts if "whose name contains" in s and "rootPane" in s]
        assert len(lookups) == 2  # panel check + tab enumeration
        assert all('return "no-window"' in s for s in lookups)


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
