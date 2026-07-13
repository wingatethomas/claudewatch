"""Tests for claudewatch.ui.session_actions.open_terminal_and_run."""

from unittest.mock import patch

_MOD = "claudewatch.ui.session_actions"

_SID = "12345678-1234-1234-1234-123456789abc"


def _run(command: str, cwd: str = "") -> str:
    with patch(f"{_MOD}.run_applescript") as mock_run:
        from claudewatch.ui.session_actions import open_terminal_and_run

        open_terminal_and_run(command, cwd)
    return mock_run.call_args.args[0]


class TestOpenTerminalAndRun:
    def test_no_positional_window_references(self) -> None:
        """Stored/positional window refs race the window opening — banned."""
        script = _run(f"claude -r {_SID}", "/Users/dev/myapp")
        assert "front window" not in script
        assert "open -a Terminal" not in script
        assert "delay" not in script

    def test_cwd_uses_quoted_form(self) -> None:
        script = _run(f"claude -r {_SID}", "/Users/dev/myapp")
        assert 'quoted form of "/Users/dev/myapp"' in script
        assert f"claude -r {_SID}" in script
        assert "activate" in script

    def test_cwd_is_escaped(self) -> None:
        script = _run("claude /usage", '/tmp/x"; do shell script "evil')
        assert '/tmp/x\\"; do shell script \\"evil' in script
        assert 'x";' not in script

    def test_command_is_escaped(self) -> None:
        script = _run('echo "hi"')
        assert 'echo \\"hi\\"' in script

    def test_no_cwd_runs_command_directly(self) -> None:
        script = _run("claude /usage")
        assert 'do script "claude /usage"' in script
        assert "quoted form of" not in script
        assert "activate" in script
