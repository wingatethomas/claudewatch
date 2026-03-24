"""Tests for claudewatch.backend.onboarding.service."""

from unittest.mock import MagicMock, patch

from claudewatch.backend.notifications.service import NotificationService
from claudewatch.backend.onboarding.service import (
    TIPS,
    OnboardingService,
    get_session_count,
    increment_session_count,
    is_tip_shown,
    show_tip,
)

# All patches target the onboarding module's references
_MOD = "claudewatch.backend.onboarding.service"


def _make_service() -> OnboardingService:
    """Create an OnboardingService with a default NotificationService."""
    return OnboardingService(NotificationService())


class TestOnboardingServiceIsBaseService:
    """OnboardingService extends BaseService."""

    def test_instance_is_onboarding_service(self):
        svc = _make_service()
        assert isinstance(svc, OnboardingService)

    def test_accepts_notification_service(self):
        nsvc = NotificationService()
        svc = OnboardingService(nsvc)
        assert svc._notification_service is nsvc


class TestTipTracking:
    """Shown-tip tracking via config."""

    def test_tip_not_shown_initially(self):
        with patch(f"{_MOD}.get_setting", return_value=[]):
            assert not is_tip_shown("welcome")

    def test_tip_shown_after_marking(self):
        with patch(f"{_MOD}.get_setting", return_value=["welcome"]):
            assert is_tip_shown("welcome")

    def test_unknown_tip_not_shown(self):
        with patch(f"{_MOD}.get_setting", return_value=["welcome"]):
            assert not is_tip_shown("nonexistent")

    def test_invalid_setting_returns_empty(self):
        with patch(f"{_MOD}.get_setting", return_value="not-a-list"):
            assert not is_tip_shown("welcome")

    def test_service_is_tip_shown(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value=["attention"]):
            assert svc.is_tip_shown("attention")
            assert not svc.is_tip_shown("welcome")


class TestShowTip:
    """Tip delivery via terminal-notifier."""

    def test_show_tip_sends_notification(self):
        mock_run = MagicMock()

        def _get(key):
            if key == "onboarding_tips_shown":
                return []
            if key == "notifications_enabled":
                return True
            return None

        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", side_effect=_get),
            patch(f"{_MOD}.set_setting"),
            patch(f"{_MOD}.subprocess.run", mock_run),
        ):
            result = show_tip("welcome")
        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/tn"
        assert "-title" in cmd
        assert TIPS["welcome"]["title"] in cmd

    def test_show_tip_marks_as_shown(self):
        mock_set = MagicMock()

        def _get(key):
            if key == "onboarding_tips_shown":
                return []
            if key == "notifications_enabled":
                return True
            return None

        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", side_effect=_get),
            patch(f"{_MOD}.set_setting", mock_set),
            patch(f"{_MOD}.subprocess.run"),
        ):
            show_tip("welcome")
        mock_set.assert_called_once_with("onboarding_tips_shown", ["welcome"])

    def test_already_shown_tip_not_resent(self):
        mock_run = MagicMock()
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=["welcome"]),
            patch(f"{_MOD}.subprocess.run", mock_run),
        ):
            result = show_tip("welcome")
        assert result is False
        mock_run.assert_not_called()

    def test_no_terminal_notifier_skips(self):
        with patch(f"{_MOD}.TERMINAL_NOTIFIER", None):
            result = show_tip("welcome")
        assert result is False

    def test_notifications_disabled_skips(self):
        def _get_setting(key):
            if key == "onboarding_tips_shown":
                return []
            if key == "notifications_enabled":
                return False
            return None

        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", side_effect=_get_setting),
        ):
            result = show_tip("welcome")
        assert result is False

    def test_unknown_tip_id_skips(self):
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=[]),
        ):
            result = show_tip("nonexistent")
        assert result is False

    def test_subprocess_failure_returns_false(self):
        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", return_value=[]),
            patch(f"{_MOD}.set_setting"),
            patch(f"{_MOD}.subprocess.run", side_effect=OSError("not found")),
        ):
            result = show_tip("welcome")
        assert result is False

    def test_service_show_tip(self):
        svc = _make_service()
        mock_run = MagicMock()

        def _get(key):
            if key == "onboarding_tips_shown":
                return []
            if key == "notifications_enabled":
                return True
            return None

        with (
            patch(f"{_MOD}.TERMINAL_NOTIFIER", "/usr/bin/tn"),
            patch(f"{_MOD}.get_setting", side_effect=_get),
            patch(f"{_MOD}.set_setting"),
            patch(f"{_MOD}.subprocess.run", mock_run),
        ):
            result = svc.show_tip("welcome")
        assert result is True
        mock_run.assert_called_once()


class TestSessionCount:
    """Cumulative session counter for hover tip threshold."""

    def test_get_session_count_default(self):
        with patch(f"{_MOD}.get_setting", return_value=0):
            assert get_session_count() == 0

    def test_get_session_count_with_value(self):
        with patch(f"{_MOD}.get_setting", return_value=7):
            assert get_session_count() == 7

    def test_get_session_count_invalid_returns_zero(self):
        with patch(f"{_MOD}.get_setting", return_value="bad"):
            assert get_session_count() == 0

    def test_increment_session_count(self):
        mock_set = MagicMock()
        with (
            patch(f"{_MOD}.get_setting", return_value=3),
            patch(f"{_MOD}.set_setting", mock_set),
        ):
            result = increment_session_count(2)
        assert result == 5
        mock_set.assert_called_once_with("onboarding_session_count", 5)

    def test_increment_default_adds_one(self):
        mock_set = MagicMock()
        with (
            patch(f"{_MOD}.get_setting", return_value=0),
            patch(f"{_MOD}.set_setting", mock_set),
        ):
            result = increment_session_count()
        assert result == 1
        mock_set.assert_called_once_with("onboarding_session_count", 1)

    def test_service_get_session_count(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value=42):
            assert svc.get_session_count() == 42

    def test_service_increment_session_count(self):
        svc = _make_service()
        mock_set = MagicMock()
        with (
            patch(f"{_MOD}.get_setting", return_value=10),
            patch(f"{_MOD}.set_setting", mock_set),
        ):
            result = svc.increment_session_count(5)
        assert result == 15
        mock_set.assert_called_once_with("onboarding_session_count", 15)


class TestMarkWelcomeShown:
    """mark_welcome_shown wraps config repo."""

    def test_mark_welcome_shown(self):
        svc = _make_service()
        mock_set = MagicMock()
        with patch(f"{_MOD}.set_setting", mock_set):
            svc.mark_welcome_shown()
        mock_set.assert_called_once_with("welcome_shown", True)


class TestTipDefinitions:
    """Verify all expected tips are defined."""

    def test_all_tip_ids_present(self):
        assert set(TIPS.keys()) == {"welcome", "attention", "pin", "hover"}

    def test_each_tip_has_title_and_message(self):
        for tip_id, tip in TIPS.items():
            assert "title" in tip, f"{tip_id} missing title"
            assert "message" in tip, f"{tip_id} missing message"
            assert len(tip["title"]) > 0
            assert len(tip["message"]) > 0
