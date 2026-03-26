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


def _mock_center():
    """Return a mock NSUserNotificationCenter with deliverNotification_."""
    return MagicMock()


def _mock_notification_class():
    """Return a mock NSUserNotification class whose alloc().init() returns a mock instance."""
    instance = MagicMock()
    cls = MagicMock()
    cls.alloc.return_value.init.return_value = instance
    return cls, instance


class TestNotificationServiceIsBaseService:
    """NotificationService extends BaseService."""

    def test_instance_is_notification_service(self):
        svc = NotificationService()
        assert isinstance(svc, NotificationService)


class TestSend:
    """send() creates and delivers an NSUserNotification."""

    def test_send_creates_and_delivers_notification(self):
        svc = NotificationService()
        mock_cls, mock_notif = _mock_notification_class()
        mock_center = _mock_center()
        svc._center = mock_center
        with (
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}.NSUserNotification", mock_cls),
        ):
            svc.send("My Title", "My Subtitle", "My Message")
        mock_notif.setTitle_.assert_called_once_with("My Title")
        mock_notif.setSubtitle_.assert_called_once_with("My Subtitle")
        mock_notif.setInformativeText_.assert_called_once_with("My Message")
        mock_center.deliverNotification_.assert_called_once_with(mock_notif)

    def test_send_skips_when_notifications_disabled(self):
        svc = NotificationService()
        mock_center = _mock_center()
        svc._center = mock_center
        with patch(f"{_MOD}.features.is_enabled", return_value=False):
            svc.send("Title", "Sub", "Msg")
        mock_center.deliverNotification_.assert_not_called()

    def test_send_truncates_long_message(self):
        svc = NotificationService()
        mock_cls, mock_notif = _mock_notification_class()
        mock_center = _mock_center()
        svc._center = mock_center
        long_msg = "x" * 500
        with (
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}.NSUserNotification", mock_cls),
        ):
            svc.send("Title", "Sub", long_msg)
        # Message should be truncated to 200 characters
        actual_msg = mock_notif.setInformativeText_.call_args[0][0]
        assert len(actual_msg) == 200


class TestNotifyIfNeeded:
    """notify_if_needed() delivers notifications for attention sessions."""

    def test_sends_for_attention_sessions(self):
        svc = NotificationService()
        svc.last_notification_time = 0.0
        mock_cls, mock_notif = _mock_notification_class()
        mock_center = _mock_center()
        svc._center = mock_center
        with (
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}.NSUserNotification", mock_cls),
            patch(f"{_MOD}._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=200, status=SessionStatus.ATTENTION)
            svc.notify_if_needed([s])
        mock_center.deliverNotification_.assert_called_once()
        assert 200 in svc._notified_pids

    def test_respects_cooldown(self):
        svc = NotificationService()
        svc.cooldown = 30.0
        svc.last_notification_time = time.time()  # just now
        mock_center = _mock_center()
        svc._center = mock_center
        with (
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=200, status=SessionStatus.ATTENTION)
            svc.notify_if_needed([s])
        mock_center.deliverNotification_.assert_not_called()

    def test_sends_after_cooldown_expires(self):
        svc = NotificationService()
        svc.cooldown = 30.0
        svc.last_notification_time = time.time() - 60  # long ago
        mock_cls, mock_notif = _mock_notification_class()
        mock_center = _mock_center()
        svc._center = mock_center
        with (
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}.NSUserNotification", mock_cls),
            patch(f"{_MOD}._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=200, status=SessionStatus.ATTENTION)
            svc.notify_if_needed([s])
        mock_center.deliverNotification_.assert_called_once()

    def test_skips_already_notified_pids(self):
        svc = NotificationService()
        svc._notified_pids = {100}
        svc.last_notification_time = 0.0
        mock_center = _mock_center()
        svc._center = mock_center
        with (
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=100, status=SessionStatus.ATTENTION)
            svc.notify_if_needed([s])
        mock_center.deliverNotification_.assert_not_called()

    def test_skips_when_frontmost_window_matches_project(self):
        svc = NotificationService()
        svc.last_notification_time = 0.0
        mock_center = _mock_center()
        svc._center = mock_center
        with (
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(
                f"{_MOD}._get_frontmost_window",
                return_value=("Terminal", "myproject — claude"),
            ),
        ):
            s = _make_session(
                pid=300,
                project="myproject",
                status=SessionStatus.ATTENTION,
            )
            svc.notify_if_needed([s])
        mock_center.deliverNotification_.assert_not_called()

    def test_sends_when_different_project_is_frontmost(self):
        svc = NotificationService()
        svc.last_notification_time = 0.0
        mock_cls, mock_notif = _mock_notification_class()
        mock_center = _mock_center()
        svc._center = mock_center
        with (
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}.NSUserNotification", mock_cls),
            patch(
                f"{_MOD}._get_frontmost_window",
                return_value=("Terminal", "other-project — claude"),
            ),
        ):
            s = _make_session(
                pid=300,
                project="myproject",
                status=SessionStatus.ATTENTION,
            )
            svc.notify_if_needed([s])
        mock_center.deliverNotification_.assert_called_once()

    def test_notification_includes_pid_in_user_info(self):
        svc = NotificationService()
        svc.last_notification_time = 0.0
        mock_cls, mock_notif = _mock_notification_class()
        mock_center = _mock_center()
        svc._center = mock_center
        with (
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}.NSUserNotification", mock_cls),
            patch(f"{_MOD}._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(pid=500, status=SessionStatus.ATTENTION)
            svc.notify_if_needed([s])
        user_info = mock_notif.setUserInfo_.call_args[0][0]
        assert user_info["pid"] == 500

    def test_notifications_disabled_skips(self):
        svc = NotificationService()
        mock_center = _mock_center()
        svc._center = mock_center
        with patch(f"{_MOD}.features.is_enabled", return_value=False):
            s = _make_session(status=SessionStatus.ATTENTION)
            svc.notify_if_needed([s])
        mock_center.deliverNotification_.assert_not_called()
        assert s.pid not in svc._notified_pids

    def test_no_attention_sessions_clears_dead_pids(self):
        svc = NotificationService()
        svc._notified_pids = {999}
        with patch(f"{_MOD}.features.is_enabled", return_value=True):
            s = _make_session(pid=100, status=SessionStatus.WORKING)
            svc.notify_if_needed([s])
        assert 999 not in svc._notified_pids

    def test_notification_includes_project_in_user_info(self):
        svc = NotificationService()
        svc.last_notification_time = 0.0
        mock_cls, mock_notif = _mock_notification_class()
        mock_center = _mock_center()
        svc._center = mock_center
        with (
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}.NSUserNotification", mock_cls),
            patch(f"{_MOD}._get_frontmost_window", return_value=("Finder", "")),
        ):
            s = _make_session(
                pid=600,
                project="myproject",
                status=SessionStatus.ATTENTION,
            )
            svc.notify_if_needed([s])
        user_info = mock_notif.setUserInfo_.call_args[0][0]
        assert user_info["project"] == "myproject"
