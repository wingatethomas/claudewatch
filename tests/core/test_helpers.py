"""Tests for claudewatch.backend.core.helpers — escape_applescript, run_applescript, is_accessibility_trusted."""

import logging
from unittest.mock import MagicMock, patch

from claudewatch.backend.core.helpers import escape_applescript, is_accessibility_trusted, run_applescript


class TestRunApplescript:
    def test_returns_result(self):
        with patch("claudewatch.backend.core.helpers.NSAppleScript") as mock_cls:
            mock_script = MagicMock()
            mock_result = MagicMock()
            mock_result.stringValue.return_value = "hello"
            mock_script.executeAndReturnError_.return_value = (mock_result, None)
            mock_cls.alloc.return_value.initWithSource_.return_value = mock_script

            assert run_applescript('return "hello"') == "hello"

    def test_returns_empty_on_error(self):
        with patch("claudewatch.backend.core.helpers.NSAppleScript") as mock_cls:
            mock_script = MagicMock()
            mock_script.executeAndReturnError_.return_value = (None, {"NSAppleScriptErrorMessage": "fail"})
            mock_cls.alloc.return_value.initWithSource_.return_value = mock_script

            assert run_applescript("bad script") == ""

    def test_returns_empty_when_result_has_no_string_value(self):
        with patch("claudewatch.backend.core.helpers.NSAppleScript") as mock_cls:
            mock_script = MagicMock()
            mock_result = MagicMock()
            mock_result.stringValue.return_value = None
            mock_script.executeAndReturnError_.return_value = (mock_result, None)
            mock_cls.alloc.return_value.initWithSource_.return_value = mock_script

            assert run_applescript("return 42") == ""


class TestEscapeApplescript:
    def test_escapes_quotes(self):
        assert escape_applescript('hello "world"') == 'hello \\"world\\"'

    def test_escapes_backslashes(self):
        assert escape_applescript("path\\to\\file") == "path\\\\to\\\\file"

    def test_strips_control_chars(self):
        result = escape_applescript("hello\r\nworld\x00test")
        assert "\r" not in result
        assert "\n" not in result
        assert "\x00" not in result
        assert "hello" in result
        assert "world" in result

    def test_preserves_tabs(self):
        assert "\t" in escape_applescript("hello\tworld")

    def test_empty_string(self):
        assert escape_applescript("") == ""

    def test_normal_string_unchanged(self):
        assert escape_applescript("hello world") == "hello world"


class TestRunApplescriptErrorLogging:
    """run_applescript logs -60005 errors at WARNING level."""

    def test_logs_warning_for_60005_error(self, caplog: object) -> None:
        with (
            patch("claudewatch.backend.core.helpers.NSAppleScript") as mock_cls,
            caplog.at_level(logging.WARNING, logger="claudewatch"),  # type: ignore[union-attr]
        ):
            mock_script = MagicMock()
            mock_script.executeAndReturnError_.return_value = (
                None,
                {"NSAppleScriptErrorMessage": "Not authorized. (-60005)"},
            )
            mock_cls.alloc.return_value.initWithSource_.return_value = mock_script

            result = run_applescript("tell application System Events")
        assert result == ""
        assert any("-60005" in r.message and r.levelno == logging.WARNING for r in caplog.records)

    def test_logs_debug_for_other_errors(self, caplog: object) -> None:
        with (
            patch("claudewatch.backend.core.helpers.NSAppleScript") as mock_cls,
            caplog.at_level(logging.DEBUG, logger="claudewatch"),  # type: ignore[union-attr]
        ):
            mock_script = MagicMock()
            mock_script.executeAndReturnError_.return_value = (
                None,
                {"NSAppleScriptErrorMessage": "Some other error"},
            )
            mock_cls.alloc.return_value.initWithSource_.return_value = mock_script

            run_applescript("bad script")
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not warning_records


class TestIsAccessibilityTrusted:
    """is_accessibility_trusted wraps AXIsProcessTrusted correctly."""

    def test_returns_true_when_trusted(self) -> None:
        with patch("claudewatch.backend.core.helpers.ctypes") as mock_ctypes:
            mock_lib = MagicMock()
            mock_lib.AXIsProcessTrusted.return_value = True
            mock_ctypes.cdll.LoadLibrary.return_value = mock_lib
            mock_ctypes.c_bool = bool

            assert is_accessibility_trusted() is True

    def test_returns_false_when_not_trusted(self) -> None:
        with patch("claudewatch.backend.core.helpers.ctypes") as mock_ctypes:
            mock_lib = MagicMock()
            mock_lib.AXIsProcessTrusted.return_value = False
            mock_ctypes.cdll.LoadLibrary.return_value = mock_lib
            mock_ctypes.c_bool = bool

            assert is_accessibility_trusted() is False

    def test_returns_false_on_oserror(self) -> None:
        with patch("claudewatch.backend.core.helpers.ctypes") as mock_ctypes:
            mock_ctypes.cdll.LoadLibrary.side_effect = OSError("not found")

            assert is_accessibility_trusted() is False
