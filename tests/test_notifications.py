"""Tests for claudewatch.backend.notifications.service."""

import time
from unittest.mock import MagicMock, patch

from claudewatch.backend.core.models import ClaudeSession, HostApp, SessionStatus
from claudewatch.backend.notifications.service import NotificationService

_MOD = "claudewatch.backend.notifications.service"


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


class TestNotificationServiceIsBaseService:
    """NotificationService extends BaseService."""

    def test_instance_is_notification_service(self):
        svc = NotificationService()
        assert isinstance(svc, NotificationService)


class TestNotificationServiceBasics:
    """Basic notification manager behavior."""

    def test_no_terminal_notifier_skips(self):
        mgr = NotificationService()
        with patch(f"{_MOD}.TERMINAL_NOTIFIER", None):
            s = _make_session(status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        assert s.pid not in mgr._notified_pids

    def test_notifications_disabled_skips(self):
        mgr = NotificationService()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=False),
        ):
            s = _make_session(status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        assert s.pid not in mgr._notified_pids

    def test_no_attention_sessions_clears_dead_pids(self):
        mgr = NotificationService()
        mgr._notified_pids = {999}
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=True),
        ):
            s = _make_session(pid=100, status=SessionStatus.WORKING)
            mgr.notify_if_needed([s])
        assert 999 not in mgr._notified_pids

    def test_already_notified_pid_skipped(self):
        mgr = NotificationService()
        mgr._notified_pids = {100}
        mock_run = MagicMock()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=True),
            patch(f"{_MOD}.subprocess.run", mock_run),
            patch(f"{_MOD}._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=100, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_run.assert_not_called()


class TestNotificationServiceCooldown:
    """Cooldown prevents notification spam."""

    def test_cooldown_prevents_second_notification(self):
        mgr = NotificationService()
        mgr.cooldown = 30.0
        mgr.last_notification_time = time.time()
        mock_run = MagicMock()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=True),
            patch(f"{_MOD}.subprocess.run", mock_run),
            patch(f"{_MOD}._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=200, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_run.assert_not_called()

    def test_notification_sent_after_cooldown(self):
        mgr = NotificationService()
        mgr.cooldown = 30.0
        mgr.last_notification_time = time.time() - 60
        mock_run = MagicMock()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=True),
            patch(f"{_MOD}.subprocess.run", mock_run),
            patch(f"{_MOD}._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=200, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_run.assert_called_once()


class TestNotificationServiceFrontWindow:
    """Skip notifications when the session window is already in focus."""

    def test_skip_when_project_is_frontmost(self):
        mgr = NotificationService()
        mgr.last_notification_time = 0.0
        mock_run = MagicMock()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=True),
            patch(f"{_MOD}.subprocess.run", mock_run),
            patch(
                f"{_MOD}._get_frontmost_window",
                return_value=("Terminal", "myproject — claude"),
            ),
        ):
            s = _make_session(pid=300, project="myproject", status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_run.assert_not_called()

    def test_notify_when_different_project_is_frontmost(self):
        mgr = NotificationService()
        mgr.last_notification_time = 0.0
        mock_run = MagicMock()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=True),
            patch(f"{_MOD}.subprocess.run", mock_run),
            patch(
                f"{_MOD}._get_frontmost_window",
                return_value=("Terminal", "other-project — claude"),
            ),
        ):
            s = _make_session(pid=300, project="myproject", status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        mock_run.assert_called_once()


class TestNotificationSend:
    """Verify subprocess call and send() method."""

    def test_pid_added_to_notified_set(self):
        mgr = NotificationService()
        mgr.last_notification_time = 0.0
        mock_run = MagicMock()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=True),
            patch(f"{_MOD}.subprocess.run", mock_run),
            patch(f"{_MOD}._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=500, status=SessionStatus.ATTENTION)
            mgr.notify_if_needed([s])
        assert 500 in mgr._notified_pids

    def test_send_calls_terminal_notifier(self):
        svc = NotificationService()
        mock_run = MagicMock()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.subprocess.run", mock_run),
        ):
            svc.send("My Title", "My Subtitle", "My Message")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/tn"
        assert "-title" in cmd
        assert "My Title" in cmd
        assert "My Subtitle" in cmd
        assert "My Message" in cmd

    def test_send_skips_without_terminal_notifier(self):
        svc = NotificationService()
        mock_run = MagicMock()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", None),
            patch(f"{_MOD}.subprocess.run", mock_run),
        ):
            svc.send("Title", "Sub", "Msg")
        mock_run.assert_not_called()

    def test_send_truncates_long_message(self):
        svc = NotificationService()
        mock_run = MagicMock()
        long_msg = "x" * 500
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.subprocess.run", mock_run),
        ):
            svc.send("Title", "Sub", long_msg)
        cmd = mock_run.call_args[0][0]
        msg_idx = cmd.index("-message") + 1
        assert len(cmd[msg_idx]) == 200

    def test_send_handles_oserror(self):
        svc = NotificationService()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.subprocess.run", side_effect=OSError("not found")),
        ):
            # Should not raise
            svc.send("Title", "Sub", "Msg")
