"""Tests for detection domain typed models."""

import pytest

from claudewatch.backend.core.models import HostApp
from claudewatch.backend.detection.models import (
    PendingToolResult,
    PromptInfo,
    TerminalMatch,
    ToolUseInfo,
)


class TestPendingToolResult:
    def test_construction(self):
        result = PendingToolResult(has_pending=True, one_line="Bash: ls", context="Tool: Bash\nCommand: ls")
        assert result.has_pending is True
        assert result.one_line == "Bash: ls"

    def test_frozen(self):
        result = PendingToolResult(has_pending=False, one_line="", context="")
        with pytest.raises(AttributeError):
            result.has_pending = True  # type: ignore[misc]

    def test_empty(self):
        result = PendingToolResult(has_pending=False, one_line="", context="")
        assert not result.has_pending
        assert result.one_line == ""


class TestToolUseInfo:
    def test_construction(self):
        info = ToolUseInfo(one_line="Edit: auth.py", context="Tool: Edit\nFile: /tmp/auth.py")
        assert "Edit" in info.one_line
        assert "File:" in info.context

    def test_frozen(self):
        info = ToolUseInfo(one_line="x", context="y")
        with pytest.raises(AttributeError):
            info.one_line = "z"  # type: ignore[misc]


class TestPromptInfo:
    def test_construction(self):
        info = PromptInfo(one_line="Bash: ls -la", context="Allow once")
        assert "Bash" in info.one_line

    def test_empty(self):
        info = PromptInfo(one_line="", context="")
        assert info.one_line == ""
        assert info.context == ""


class TestTerminalMatch:
    def test_construction(self):
        match = TerminalMatch(window_title="myapp — claude", window_id=42, host_app=HostApp.TERMINAL)
        assert match.window_title == "myapp — claude"
        assert match.window_id == 42
        assert match.host_app == HostApp.TERMINAL

    def test_no_window_id(self):
        match = TerminalMatch(window_title="PyCharm", window_id=None, host_app=HostApp.PYCHARM)
        assert match.window_id is None

    def test_frozen(self):
        match = TerminalMatch(window_title="x", window_id=1, host_app=HostApp.TERMINAL)
        with pytest.raises(AttributeError):
            match.window_title = "y"  # type: ignore[misc]
