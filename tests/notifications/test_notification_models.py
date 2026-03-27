"""Tests for notification domain typed models."""

import pytest

from claudewatch.backend.notifications.models import FrontmostWindow


class TestFrontmostWindow:
    def test_construction(self):
        fw = FrontmostWindow(app_name="Terminal", window_title="myapp — claude")
        assert fw.app_name == "Terminal"
        assert fw.window_title == "myapp — claude"

    def test_frozen(self):
        fw = FrontmostWindow(app_name="x", window_title="y")
        with pytest.raises(AttributeError):
            fw.app_name = "z"  # type: ignore[misc]

    def test_empty(self):
        fw = FrontmostWindow(app_name="", window_title="")
        assert fw.app_name == ""
        assert fw.window_title == ""
