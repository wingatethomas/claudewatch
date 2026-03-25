"""Tests for pure helpers in claudewatch.ui.preferences."""

from unittest.mock import patch

from claudewatch.ui.preferences import _display_path


class TestDisplayPath:
    def test_shortens_home_prefix(self):
        with patch("claudewatch.ui.preferences.os.path.expanduser", return_value="/Users/dev"):
            assert _display_path("/Users/dev/projects") == "~/projects"

    def test_preserves_non_home_path(self):
        with patch("claudewatch.ui.preferences.os.path.expanduser", return_value="/Users/dev"):
            assert _display_path("/opt/work") == "/opt/work"

    def test_home_alone_returns_tilde(self):
        with patch("claudewatch.ui.preferences.os.path.expanduser", return_value="/Users/dev"):
            assert _display_path("/Users/dev") == "~"

    def test_empty_string(self):
        assert _display_path("") == ""
