"""Tests for pure functions in claudewatch.backend.services.detection."""

from unittest.mock import patch

from claudewatch.backend.models import HostApp, SessionStatus
from claudewatch.backend.services.detection import (
    _batch_lsof_cwds,
    _batch_ps_info,
    _detect_host_app,
    _determine_status,
    _extract_last_output,
    _extract_prompt_info,
    _format_tool_use,
    _host_app_cache,
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


class TestBatchPsInfo:
    """Tests for _batch_ps_info() with mocked procinfo output."""

    @patch("claudewatch.backend.services.detection.get_process_info")
    def test_returns_process_info(self, mock_get):
        mock_get.return_value = {
            1234: {"tty": "ttys001", "ppid": 5678, "comm": "/usr/bin/zsh"},
            1235: {"tty": "ttys002", "ppid": 5679, "comm": "/usr/bin/bash"},
        }
        result = _batch_ps_info([1234, 1235])
        assert 1234 in result
        assert result[1234]["tty"] == "ttys001"
        assert result[1234]["ppid"] == 5678
        assert result[1234]["comm"] == "/usr/bin/zsh"
        assert result[1235]["tty"] == "ttys002"

    @patch("claudewatch.backend.services.detection.get_process_info")
    def test_empty_pids(self, mock_get):
        mock_get.return_value = {}
        assert _batch_ps_info([]) == {}

    @patch("claudewatch.backend.services.detection.get_process_info")
    def test_comm_with_path(self, mock_get):
        mock_get.return_value = {
            1234: {"tty": "ttys001", "ppid": 5678, "comm": "/Applications/Code Helper (Plugin)"},
        }
        result = _batch_ps_info([1234])
        assert result[1234]["comm"] == "/Applications/Code Helper (Plugin)"


class TestBatchLsofCwds:
    """Tests for _batch_lsof_cwds() with mocked procinfo output."""

    @patch("claudewatch.backend.services.detection.get_cwds")
    def test_returns_cwds(self, mock_get):
        mock_get.return_value = {
            1234: "/Users/dev/myapp",
            1235: "/Users/dev/other",
        }
        result = _batch_lsof_cwds([1234, 1235])
        assert result[1234] == "/Users/dev/myapp"
        assert result[1235] == "/Users/dev/other"

    @patch("claudewatch.backend.services.detection.get_cwds")
    def test_empty_pids(self, mock_get):
        mock_get.return_value = {}
        assert _batch_lsof_cwds([]) == {}

    @patch("claudewatch.backend.services.detection.get_cwds")
    def test_pid_without_cwd(self, mock_get):
        mock_get.return_value = {1235: "/Users/dev/other"}
        result = _batch_lsof_cwds([1234, 1235])
        assert 1234 not in result
        assert result[1235] == "/Users/dev/other"

    @patch("claudewatch.backend.services.detection.get_cwds")
    def test_empty_result(self, mock_get):
        mock_get.return_value = {}
        assert _batch_lsof_cwds([1234]) == {}


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


class TestDetectHostApp:
    """Tests for _detect_host_app() with mocked process tree."""

    def setup_method(self):
        _host_app_cache.clear()

    def test_finds_terminal_in_ppid_chain(self):
        all_ps = {
            100: {"tty": "ttys001", "ppid": 200, "comm": "/usr/bin/zsh"},
            200: {"tty": "??", "ppid": 300, "comm": "/usr/bin/login"},
            300: {
                "tty": "??",
                "ppid": 1,
                "comm": "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal",
            },
        }
        assert _detect_host_app(100, all_ps) == HostApp.TERMINAL

    def test_finds_pycharm(self):
        all_ps = {
            100: {"tty": "ttys001", "ppid": 200, "comm": "/usr/bin/zsh"},
            200: {"tty": "??", "ppid": 1, "comm": "/Applications/PyCharm.app/Contents/MacOS/pycharm"},
        }
        assert _detect_host_app(100, all_ps) == HostApp.PYCHARM

    def test_finds_tmux(self):
        all_ps = {
            100: {"tty": "ttys001", "ppid": 200, "comm": "/usr/bin/zsh"},
            200: {"tty": "??", "ppid": 1, "comm": "tmux: server"},
        }
        assert _detect_host_app(100, all_ps) == HostApp.TMUX

    def test_caches_result(self):
        all_ps = {
            100: {"tty": "ttys001", "ppid": 200, "comm": "/usr/bin/zsh"},
            200: {"tty": "??", "ppid": 1, "comm": "Terminal"},
        }
        _detect_host_app(100, all_ps)
        assert 100 in _host_app_cache
        assert _host_app_cache[100] == HostApp.TERMINAL

    def test_returns_other_when_no_match(self):
        all_ps = {
            100: {"tty": "ttys001", "ppid": 1, "comm": "/usr/bin/zsh"},
        }
        assert _detect_host_app(100, all_ps) == HostApp.OTHER

    @patch("claudewatch.backend.services.detection.get_single_process_info")
    def test_falls_back_to_procinfo_for_missing_ppid(self, mock_get_single):
        all_ps = {
            100: {"tty": "ttys001", "ppid": 200, "comm": "/usr/bin/zsh"},
            # 200 not in all_ps — will call get_single_process_info
        }
        mock_get_single.return_value = {
            "tty": "??",
            "ppid": 1,
            "comm": "/Applications/PyCharm.app/Contents/MacOS/pycharm",
        }
        assert _detect_host_app(100, all_ps) == HostApp.PYCHARM
