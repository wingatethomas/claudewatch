"""Tests for pure functions in claudewatch.backend.detection.service."""

from claudewatch.backend.core.models import HostApp, SessionStatus
from claudewatch.backend.detection.service import (
    _determine_status,
    _format_tool_use,
    _match_terminal_window,
)


class TestFormatToolUse:
    """Tests for _format_tool_use()."""

    def test_command_tool(self):
        tool = {"name": "Bash", "input": {"command": "ls -la /tmp"}}
        result = _format_tool_use(tool)
        assert "Bash" in result.one_line
        assert "ls -la" in result.one_line
        assert "Command:" in result.context

    def test_file_tool(self):
        tool = {"name": "Edit", "input": {"file_path": "/tmp/auth.py"}}
        result = _format_tool_use(tool)
        assert "Edit" in result.one_line
        assert "auth.py" in result.one_line
        assert "File:" in result.context

    def test_pattern_tool(self):
        tool = {"name": "Grep", "input": {"pattern": "def login"}}
        result = _format_tool_use(tool)
        assert "Grep" in result.one_line
        assert "def login" in result.one_line

    def test_unknown_tool(self):
        tool = {"name": "CustomTool", "input": {}}
        result = _format_tool_use(tool)
        assert result.one_line == "CustomTool"

    def test_truncates_long_command(self):
        tool = {"name": "Bash", "input": {"command": "x" * 100}}
        result = _format_tool_use(tool)
        assert len(result.one_line) <= 80


class TestDetermineStatus:
    """Tests for _determine_status()."""

    def test_idle_indicator(self):
        assert _determine_status("myapp \u2014 \u2733 Done") == SessionStatus.IDLE

    def test_working_no_indicator(self):
        assert _determine_status("myapp \u2014 \u25cf Running") == SessionStatus.WORKING

    def test_empty_title(self):
        assert _determine_status("") == SessionStatus.WORKING


class TestMatchTerminalWindow:
    """Tests for _match_terminal_window()."""

    def test_direct_tty_match(self):
        windows = {"/dev/ttys001": ("myapp \u2014 \u2733 Done", 42)}
        result = _match_terminal_window("ttys001", "myapp", HostApp.TERMINAL, windows)
        assert result.window_title == "myapp \u2014 \u2733 Done"
        assert result.window_id == 42
        assert result.host_app == HostApp.TERMINAL

    def test_tty_with_dev_prefix(self):
        windows = {"/dev/ttys001": ("myapp", 42)}
        result = _match_terminal_window("/dev/ttys001", "myapp", HostApp.TERMINAL, windows)
        assert result.window_id == 42

    def test_upgrades_other_to_terminal(self):
        windows = {"/dev/ttys001": ("myapp", 42)}
        result = _match_terminal_window("ttys001", "myapp", HostApp.OTHER, windows)
        assert result.host_app == HostApp.TERMINAL

    def test_tmux_fallback_by_project_name(self):
        windows = {"/dev/ttys099": ("tmux: myapp \u2014 session", 99)}
        result = _match_terminal_window("ttys001", "myapp", HostApp.TMUX, windows)
        assert result.window_id == 99
        assert "myapp" in result.window_title
        assert result.host_app == HostApp.TMUX

    def test_no_match_returns_host_app_value(self):
        windows = {"/dev/ttys099": ("other project", 99)}
        result = _match_terminal_window("ttys001", "myapp", HostApp.PYCHARM, windows)
        assert result.window_title == "PyCharm"
        assert result.window_id is None
        assert result.host_app == HostApp.PYCHARM

    def test_empty_windows(self):
        result = _match_terminal_window("ttys001", "myapp", HostApp.TERMINAL, {})
        assert result.window_title == "Terminal"
        assert result.window_id is None
