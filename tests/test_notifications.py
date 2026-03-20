"""Tests for claudewatch.backend.services.notifications."""

import time
from unittest.mock import MagicMock, patch

from claudewatch.backend.models import ClaudeSession, HostApp, SessionStatus
from claudewatch.backend.services.notifications import NotificationManager


def _make_session(**kwargs):
    """Create a ClaudeSession with sensible defaults."""
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


class TestNotificationManagerBasics:
    """Basic notification manager behavior."""

    def test_no_terminal_notifier_skips(self):
        mgr = NotificationManager()
        with patch("claudewatch.backend.services.notifications.TERMINAL_NOTIFIER", None):
            s = _make_session(status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        assert s.pid not in mgr._notified_pids

    def test_notifications_disabled_skips(self):
        mgr = NotificationManager()
        with (
            patch("claudewatch.backend.services.notifications.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch("claudewatch.backend.services.notifications.get_setting", return_value=False),
        ):
            s = _make_session(status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        assert s.pid not in mgr._notified_pids

    def test_no_attention_sessions_clears_dead_pids(self):
        mgr = NotificationManager()
        mgr._notified_pids = {999}
        with (
            patch("claudewatch.backend.services.notifications.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
        ):
            s = _make_session(pid=100, status=SessionStatus.WORKING)
            mgr.notify_if_needed([s])
        assert 999 not in mgr._notified_pids

    def test_already_notified_pid_skipped(self):
        mgr = NotificationManager()
        mgr._notified_pids = {100}
        mock_run = MagicMock()
        with (
            patch("claudewatch.backend.services.notifications.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications.subprocess.run", mock_run),
            patch("claudewatch.backend.services.notifications._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=100, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_run.assert_not_called()


class TestNotificationManagerCooldown:
    """Cooldown prevents notification spam."""

    def test_cooldown_prevents_second_notification(self):
        mgr = NotificationManager()
        mgr.cooldown = 30.0
        mgr.last_notification_time = time.time()
        mock_run = MagicMock()
        with (
            patch("claudewatch.backend.services.notifications.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications.subprocess.run", mock_run),
            patch("claudewatch.backend.services.notifications._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=200, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_run.assert_not_called()

    def test_notification_sent_after_cooldown(self):
        mgr = NotificationManager()
        mgr.cooldown = 30.0
        mgr.last_notification_time = time.time() - 60
        mock_run = MagicMock()
        with (
            patch("claudewatch.backend.services.notifications.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications.subprocess.run", mock_run),
            patch("claudewatch.backend.services.notifications._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=200, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_run.assert_called_once()


class TestNotificationManagerFrontWindow:
    """Skip notifications when the session window is already in focus."""

    def test_skip_when_project_is_frontmost(self):
        mgr = NotificationManager()
        mgr.last_notification_time = 0.0
        mock_run = MagicMock()
        with (
            patch("claudewatch.backend.services.notifications.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications.subprocess.run", mock_run),
            patch(
                "claudewatch.backend.services.notifications._get_frontmost_window",
                return_value=("Terminal", "myproject — claude"),
            ),
        ):
            s = _make_session(pid=300, project="myproject", status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_run.assert_not_called()

    def test_notify_when_different_project_is_frontmost(self):
        mgr = NotificationManager()
        mgr.last_notification_time = 0.0
        mock_run = MagicMock()
        with (
            patch("claudewatch.backend.services.notifications.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications.subprocess.run", mock_run),
            patch(
                "claudewatch.backend.services.notifications._get_frontmost_window",
                return_value=("Terminal", "other-project — claude"),
            ),
        ):
            s = _make_session(pid=300, project="myproject", status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_run.assert_called_once()


class TestNotificationSend:
    """Verify subprocess call."""

    def test_pid_added_to_notified_set(self):
        mgr = NotificationManager()
        mgr.last_notification_time = 0.0
        mock_run = MagicMock()
        with (
            patch("claudewatch.backend.services.notifications.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch("claudewatch.backend.services.notifications.get_setting", return_value=True),
            patch("claudewatch.backend.services.notifications.subprocess.run", mock_run),
            patch("claudewatch.backend.services.notifications._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=500, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        assert 500 in mgr._notified_pids
