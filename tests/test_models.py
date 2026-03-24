"""Tests for claudewatch.backend.models."""

import os

from claudewatch.backend.models import (
    STATUS_INDICATOR,
    ClaudeSession,
    HostApp,
    SessionStatus,
    cwd_to_proj_key,
    proj_key_to_cwd,
)


class TestClaudeSession:
    """Tests for ClaudeSession dataclass properties."""

    def test_task_summary_with_idle_indicator(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            window_title="myapp — ✳ Fix login bug — claude TMPDIR=/tmp",
        )
        assert s.task_summary == "Fix login bug"

    def test_task_summary_with_working_indicator(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            window_title="myapp — ● Running tests — claude TMPDIR=/tmp",
        )
        assert s.task_summary == "Running tests"

    def test_task_summary_no_task(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            window_title="myapp",
        )
        assert s.task_summary == ""

    def test_needs_attention_true(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            status=SessionStatus.ATTENTION,
        )
        assert s.needs_attention is True

    def test_needs_attention_false(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            status=SessionStatus.WORKING,
        )
        assert s.needs_attention is False

    def test_menu_label_with_task(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            window_title="myapp — ✳ Fix login bug — claude TMPDIR=/tmp",
        )
        assert s.menu_label == "✦ myapp — Fix login bug"

    def test_menu_label_without_task(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
        )
        assert s.menu_label == "✦ myapp"

    def test_menu_label_with_tab_index(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.PYCHARM,
            tab_index=2,
        )
        assert "(tab 3)" in s.menu_label

    def test_detail_line_attention_with_prompt(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            status=SessionStatus.ATTENTION,
            prompt_text="Edit: auth.py",
        )
        assert s.detail_line == "Edit: auth.py"

    def test_detail_line_working(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            status=SessionStatus.WORKING,
        )
        assert s.detail_line == "Working..."

    def test_detail_line_with_last_output(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            status=SessionStatus.WORKING,
            last_output="Reading file auth.py",
        )
        assert s.detail_line == "Reading file auth.py"

    def test_detail_line_idle_no_output(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            status=SessionStatus.IDLE,
        )
        assert s.detail_line == "Waiting for input"

    def test_menu_label_filters_claude_code_task(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            window_title="myapp — ✳ Claude Code — claude TMPDIR=/tmp",
        )
        # "Claude Code" task should be filtered out of label
        assert s.menu_label == "✦ myapp"

    def test_task_summary_with_braille_spinner(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            window_title="myapp — ⠋ Running tests — claude TMPDIR=/tmp",
        )
        assert s.task_summary == "Running tests"

    def test_task_summary_with_different_braille_frame(self):
        s = ClaudeSession(
            pid=1,
            tty="ttys001",
            project="myapp",
            cwd="/tmp/myapp",
            host_app=HostApp.TERMINAL,
            window_title="myapp — ⠙ Editing files — claude TMPDIR=/tmp",
        )
        assert s.task_summary == "Editing files"


class TestPathMapping:
    """Tests for cwd_to_proj_key and proj_key_to_cwd."""

    def test_cwd_to_proj_key_basic(self):
        assert cwd_to_proj_key("/Users/dev/myapp") == "-Users-dev-myapp"

    def test_cwd_to_proj_key_root(self):
        assert cwd_to_proj_key("/") == "-"

    def test_proj_key_to_cwd_no_hyphens(self):
        assert proj_key_to_cwd("-Users-dev-myapp") == "/Users/dev/myapp"

    def test_roundtrip_simple(self):
        cwd = "/Users/dev/projects/myapp"
        assert proj_key_to_cwd(cwd_to_proj_key(cwd)) == cwd

    def test_resolves_real_hyphenated_dirs(self):
        """Validates against real ~/Develop directories if they exist."""
        test_dir = os.path.expanduser("~/Develop/backend-api")
        if os.path.isdir(test_dir):
            key = cwd_to_proj_key(test_dir)
            assert proj_key_to_cwd(key) == test_dir

    def test_proj_key_without_leading_dash(self):
        assert proj_key_to_cwd("relative-path") == "relative/path"

    def test_prefers_longest_hyphenated_match(self, tmp_path):
        """When both 'foo-bar' and 'foo-bar-baz' exist, prefer the longer match."""
        (tmp_path / "foo-bar").mkdir()
        (tmp_path / "foo-bar-baz").mkdir()
        key = cwd_to_proj_key(str(tmp_path / "foo-bar-baz"))
        assert proj_key_to_cwd(key) == str(tmp_path / "foo-bar-baz")

    def test_short_match_when_subdirs_exist(self, tmp_path):
        """When only 'foo-bar' exists, correctly split remaining as subdirs."""
        base = tmp_path / "foo-bar" / "sub"
        base.mkdir(parents=True)
        key = cwd_to_proj_key(str(base))
        assert proj_key_to_cwd(key) == str(base)

    def test_falls_back_to_slash_when_no_dir_exists(self):
        # When path doesn't exist on disk, defaults to slash separator
        result = proj_key_to_cwd("-nonexistent-path-with-hyphens")
        assert result == "/nonexistent/path/with/hyphens"


class TestEnums:
    """Tests for enum values and constants."""

    def test_host_app_values(self):
        assert HostApp.TERMINAL.value == "Terminal"
        assert HostApp.PYCHARM.value == "PyCharm"
        assert HostApp.VSCODE.value == "VS Code"

    def test_session_status_values(self):
        assert SessionStatus.WORKING.value == "working"
        assert SessionStatus.IDLE.value == "idle"
        assert SessionStatus.ATTENTION.value == "attention"

    def test_status_indicators(self):
        assert STATUS_INDICATOR[SessionStatus.WORKING] == "✦"
        assert STATUS_INDICATOR[SessionStatus.IDLE] == "⏸"
        assert STATUS_INDICATOR[SessionStatus.ATTENTION] == "⚠"
