"""Tests for claudewatch.backend.services.notifications."""

import time
from unittest.mock import MagicMock, patch

from claudewatch.backend.models import ClaudeSession, HostApp, SessionStatus
from claudewatch.backend.services.notifications import (
    NotificationManager,
    _build_focus_data,
)


def _make_session(**kwargs):
    """Create a ClaudeSession with sensible defaults, overridden by kwargs."""
    defaults = {
        "pid": 100,
        "tty": "ttys001",
        "project": "testproject",
        "cwd": "/tmp/testproject",
        "host_app": HostApp.TERMINAL,
        "status": SessionStatus.WORKING,
    }
    defaults.update(kwargs)
    return ClaudeSession(**defaults)


class TestBuildFocusData:
    """Tests for _build_focus_data — builds click callback data dict."""

    def test_terminal_with_window_id(self):
        s = _make_session(host_app=HostApp.TERMINAL, window_id=42)
        data = _build_focus_data(s)
        assert data["host_app"] == "Terminal"
        assert data["window_id"] == 42
        assert data["pid"] == s.pid

    def test_terminal_without_window_id(self):
        s = _make_session(host_app=HostApp.TERMINAL, window_id=None)
        data = _build_focus_data(s)
        assert "window_id" not in data

    def test_pycharm(self):
        s = _make_session(host_app=HostApp.PYCHARM, project="myapp")
        data = _build_focus_data(s)
        assert data["host_app"] == "PyCharm"
        assert data["project"] == "myapp"

    def test_vscode(self):
        s = _make_session(host_app=HostApp.VSCODE, project="myapp")
        data = _build_focus_data(s)
        assert data["host_app"] == "VS Code"
        assert data["project"] == "myapp"

    def test_other_host(self):
        s = _make_session(host_app=HostApp.OTHER)
        data = _build_focus_data(s)
        assert data["host_app"] == "Other"
        assert "window_id" not in data


class TestNotificationManagerBasics:
    """Basic notification manager behavior."""

    def test_notifications_disabled_skips(self):
        mgr = NotificationManager()
        mock_send = MagicMock()
        with (
            patch("claudewatch.backend.services.notifications.get_setting", return_value=False),
            patch("claudewatch.backend.services.notifications._send_notification", mock_send),
        ):
            s = _make_session(status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_send.assert_not_called()

    def test_no_attention_sessions_clears_dead_pids(self):
        mgr = NotificationManager()
        mgr._notified_pids = {999}
        with patch("claudewatch.backend.services.notifications.get_setting", return_value=True):
            s = _make_session(pid=100, status=SessionStatus.WORKING)
            mgr.notify_if_needed([s])
        assert 999 not in mgr._notified_pids

    def test_already_notified_pid_skipped(self):
        mgr = NotificationManager()
        mgr._notified_pids = {100}
        mock_send = MagicMock()
        with (
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications._send_notification", mock_send),
            patch("claudewatch.backend.services.notifications._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=100, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_send.assert_not_called()


class TestNotificationManagerCooldown:
    """Cooldown prevents notification spam."""

    def test_cooldown_prevents_second_notification(self):
        mgr = NotificationManager()
        mgr.cooldown = 30.0
        mgr.last_notification_time = time.time()
        mock_send = MagicMock()
        with (
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications._send_notification", mock_send),
            patch("claudewatch.backend.services.notifications._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=200, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_send.assert_not_called()

    def test_notification_sent_after_cooldown(self):
        mgr = NotificationManager()
        mgr.cooldown = 30.0
        mgr.last_notification_time = time.time() - 60
        mock_send = MagicMock(return_value=True)
        with (
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications._send_notification", mock_send),
            patch("claudewatch.backend.services.notifications._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=200, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_send.assert_called_once()


class TestNotificationManagerFrontWindow:
    """Skip notifications when the session window is already in focus."""

    def test_skip_when_project_is_frontmost(self):
        mgr = NotificationManager()
        mgr.last_notification_time = 0.0
        mock_send = MagicMock()
        with (
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications._send_notification", mock_send),
            patch(
                "claudewatch.backend.services.notifications._get_frontmost_window",
                return_value=("Terminal", "myproject — claude"),
            ),
        ):
            s = _make_session(pid=300, project="myproject", status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_send.assert_not_called()

    def test_notify_when_different_project_is_frontmost(self):
        mgr = NotificationManager()
        mgr.last_notification_time = 0.0
        mock_send = MagicMock(return_value=True)
        with (
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications._send_notification", mock_send),
            patch(
                "claudewatch.backend.services.notifications._get_frontmost_window",
                return_value=("Terminal", "other-project — claude"),
            ),
        ):
            s = _make_session(pid=300, project="myproject", status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_send.assert_called_once()


class TestNotificationSend:
    """Verify _send_notification is called with correct args."""

    def test_notification_content(self):
        mgr = NotificationManager()
        mgr.last_notification_time = 0.0
        mock_send = MagicMock(return_value=True)
        with (
            patch("claudewatch.backend.services.notifications.get_setting", side_effect=lambda k: {
                "notifications_enabled": True,
                "notification_sound": "Glass",
            }[k]),
            patch("claudewatch.backend.services.notifications._send_notification", mock_send),
            patch("claudewatch.backend.services.notifications._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=400, project="myapp", status=SessionStatus.ATTENTION, prompt_text="Bash: ls")
            mgr.notify_if_needed([s])
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        assert call_kwargs[1]["title"] == "Claude needs approval"
        assert call_kwargs[1]["subtitle"] == "myapp"
        assert "Bash: ls" in call_kwargs[1]["message"]
        assert call_kwargs[1]["sound_name"] == "Glass"

    def test_pid_added_to_notified_set(self):
        mgr = NotificationManager()
        mgr.last_notification_time = 0.0
        mock_send = MagicMock(return_value=True)
        with (
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications._send_notification", mock_send),
            patch("claudewatch.backend.services.notifications._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=500, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        assert 500 in mgr._notified_pids
