"""Tests for claudewatch.backend.core.helpers — escape_applescript and run_applescript."""

from unittest.mock import MagicMock, patch

from claudewatch.backend.core.helpers import escape_applescript, run_applescript


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
