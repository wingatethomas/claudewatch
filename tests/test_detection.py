"""Tests for pure functions in claudewatch.backend.detection.service."""

from claudewatch.backend.core.models import HostApp, SessionStatus
from claudewatch.backend.detection.service import (
    _determine_status,
    _extract_last_output,
    _extract_prompt_info,
    _format_tool_use,
    _match_terminal_window,
)


class TestExtractLastOutput:
    """Tests for _extract_last_output()."""

    def test_finds_claude_output_line(self):
        buffer = "some stuff\n\u23fa Reading file auth.py\n\n"
        assert _extract_last_output(buffer) == "Reading file auth.py"

    def test_returns_last_output_line(self):
        buffer = "\u23fa First line\n\u23fa Second line\n"
        assert _extract_last_output(buffer) == "Second line"

    def test_truncates_long_output(self):
        buffer = "\u23fa " + "x" * 100 + "\n"
        result = _extract_last_output(buffer)
        assert len(result) <= 80
        assert result.endswith("...")

    def test_empty_buffer(self):
        assert _extract_last_output("") == ""

    def test_no_claude_output(self):
        buffer = "just some terminal output\nno claude lines here\n"
        assert _extract_last_output(buffer) == ""

    def test_skips_empty_claude_lines(self):
        buffer = "\u23fa Real output\n\u23fa \n\u23fa\n"
        assert _extract_last_output(buffer) == "Real output"


class TestExtractPromptInfo:
    """Tests for _extract_prompt_info()."""

    def test_finds_permission_prompt(self):
        buffer = "\u23fa Update(auth.py)\n  Do you want to proceed with this edit?\n  Yes, allow | No\n"
        one_line, context = _extract_prompt_info(buffer)
        assert "Update" in one_line or "auth" in one_line
        assert "allow" in context.lower() or "Update" in context

    def test_no_prompt_returns_empty(self):
        buffer = "\u23fa Working on something\nno prompts here\n"
        one_line, context = _extract_prompt_info(buffer)
        assert one_line == ""
        assert context == ""

    def test_truncates_long_one_line(self):
        buffer = "\u23fa " + "x" * 100 + "\n  yes, allow\n"
        one_line, _ = _extract_prompt_info(buffer)
        assert len(one_line) <= 80


class TestFormatToolUse:
    """Tests for _format_tool_use()."""

    def test_command_tool(self):
        tool = {"name": "Bash", "input": {"command": "ls -la /tmp"}}
        one_line, context = _format_tool_use(tool)
        assert "Bash" in one_line
        assert "ls -la" in one_line
        assert "Command:" in context

    def test_file_tool(self):
        tool = {"name": "Edit", "input": {"file_path": "/tmp/auth.py"}}
        one_line, context = _format_tool_use(tool)
        assert "Edit" in one_line
        assert "auth.py" in one_line
        assert "File:" in context

    def test_pattern_tool(self):
        tool = {"name": "Grep", "input": {"pattern": "def login"}}
        one_line, context = _format_tool_use(tool)
        assert "Grep" in one_line
        assert "def login" in one_line

    def test_unknown_tool(self):
        tool = {"name": "CustomTool", "input": {}}
        one_line, context = _format_tool_use(tool)
        assert one_line == "CustomTool"

    def test_truncates_long_command(self):
        tool = {"name": "Bash", "input": {"command": "x" * 100}}
        one_line, _ = _format_tool_use(tool)
        assert len(one_line) <= 80


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
        title, wid, app = _match_terminal_window("ttys001", "myapp", HostApp.TERMINAL, windows)
        assert title == "myapp \u2014 \u2733 Done"
        assert wid == 42
        assert app == HostApp.TERMINAL

    def test_tty_with_dev_prefix(self):
        windows = {"/dev/ttys001": ("myapp", 42)}
        title, wid, app = _match_terminal_window("/dev/ttys001", "myapp", HostApp.TERMINAL, windows)
        assert wid == 42

    def test_upgrades_other_to_terminal(self):
        windows = {"/dev/ttys001": ("myapp", 42)}
        _, _, app = _match_terminal_window("ttys001", "myapp", HostApp.OTHER, windows)
        assert app == HostApp.TERMINAL

    def test_tmux_fallback_by_project_name(self):
        windows = {"/dev/ttys099": ("tmux: myapp \u2014 session", 99)}
        title, wid, app = _match_terminal_window("ttys001", "myapp", HostApp.TMUX, windows)
        assert wid == 99
        assert "myapp" in title
        assert app == HostApp.TMUX

    def test_no_match_returns_host_app_value(self):
        windows = {"/dev/ttys099": ("other project", 99)}
        title, wid, app = _match_terminal_window("ttys001", "myapp", HostApp.PYCHARM, windows)
        assert title == "PyCharm"
        assert wid is None
        assert app == HostApp.PYCHARM

    def test_empty_windows(self):
        title, wid, app = _match_terminal_window("ttys001", "myapp", HostApp.TERMINAL, {})
        assert title == "Terminal"
        assert wid is None


