"""Tests for claudewatch.backend.onboarding.service."""

from unittest.mock import MagicMock, patch

from claudewatch.backend.onboarding.service import (
    TIPS,
    OnboardingService,
)

# All patches target the onboarding module's references
_MOD = "claudewatch.backend.onboarding.service"


def _make_service() -> OnboardingService:
    """Create an OnboardingService with a mock NotificationService."""
    mock_nsvc = MagicMock()
    return OnboardingService(mock_nsvc)


class TestOnboardingServiceIsBaseService:
    """OnboardingService extends BaseService."""

    def test_instance_is_onboarding_service(self):
        svc = _make_service()
        assert isinstance(svc, OnboardingService)

    def test_accepts_notification_service(self):
        nsvc = MagicMock()
        svc = OnboardingService(nsvc)
        assert svc._notification_service is nsvc


class TestTipTracking:
    """Shown-tip tracking via config."""

    def test_tip_not_shown_initially(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value=[]):
            assert not svc.is_tip_shown("welcome")

    def test_tip_shown_after_marking(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value=["welcome"]):
            assert svc.is_tip_shown("welcome")

    def test_unknown_tip_not_shown(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value=["welcome"]):
            assert not svc.is_tip_shown("nonexistent")

    def test_invalid_setting_returns_empty(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value="not-a-list"):
            assert not svc.is_tip_shown("welcome")

    def test_service_is_tip_shown(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value=["attention"]):
            assert svc.is_tip_shown("attention")
            assert not svc.is_tip_shown("welcome")


class TestShowTip:
    """Tip delivery via NotificationService.send()."""

    def test_show_tip_sends_notification(self):
        svc = _make_service()

        with (
            patch(f"{_MOD}.get_setting", return_value=[]),
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}.set_setting"),
        ):
            result = svc.show_tip("welcome")
        assert result is True
        svc._notification_service.send.assert_called_once_with(
            TIPS["welcome"]["title"],
            "ClaudeWatch",
            TIPS["welcome"]["message"],
        )

    def test_show_tip_marks_as_shown(self):
        svc = _make_service()
        mock_set = MagicMock()

        with (
            patch(f"{_MOD}.get_setting", return_value=[]),
            patch(f"{_MOD}.features.is_enabled", return_value=True),
            patch(f"{_MOD}.set_setting", mock_set),
        ):
            svc.show_tip("welcome")
        mock_set.assert_called_once_with("onboarding_tips_shown", ["welcome"])

    def test_already_shown_tip_not_resent(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value=["welcome"]):
            result = svc.show_tip("welcome")
        assert result is False
        svc._notification_service.send.assert_not_called()

    def test_notifications_disabled_skips(self):
        svc = _make_service()

        with (
            patch(f"{_MOD}.get_setting", return_value=[]),
            patch(f"{_MOD}.features.is_enabled", return_value=False),
        ):
            result = svc.show_tip("welcome")
        assert result is False
        svc._notification_service.send.assert_not_called()

    def test_unknown_tip_id_skips(self):
        svc = _make_service()

        with (
            patch(f"{_MOD}.get_setting", return_value=[]),
            patch(f"{_MOD}.features.is_enabled", return_value=True),
        ):
            result = svc.show_tip("nonexistent")
        assert result is False
        svc._notification_service.send.assert_not_called()


class TestSessionCount:
    """Cumulative session counter for hover tip threshold."""

    def test_get_session_count_default(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value=0):
            assert svc.get_session_count() == 0

    def test_get_session_count_with_value(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value=7):
            assert svc.get_session_count() == 7

    def test_get_session_count_invalid_returns_zero(self):
        svc = _make_service()
        with patch(f"{_MOD}.get_setting", return_value="bad"):
            assert svc.get_session_count() == 0

    def test_increment_session_count(self):
        svc = _make_service()
        mock_set = MagicMock()
        with (
            patch(f"{_MOD}.get_setting", return_value=3),
            patch(f"{_MOD}.set_setting", mock_set),
        ):
            result = svc.increment_session_count(2)
        assert result == 5
        mock_set.assert_called_once_with("onboarding_session_count", 5)

    def test_increment_default_adds_one(self):
        svc = _make_service()
        mock_set = MagicMock()
        with (
            patch(f"{_MOD}.get_setting", return_value=0),
            patch(f"{_MOD}.set_setting", mock_set),
        ):
            result = svc.increment_session_count()
        assert result == 1
        mock_set.assert_called_once_with("onboarding_session_count", 1)


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
