"""Service dependency wiring — factory functions for service instantiation."""

from claudewatch.backend.core.services.process import ProcessService
from claudewatch.backend.core.services.session_log import SessionLogService
from claudewatch.backend.services.bookmark import BookmarkService
from claudewatch.backend.services.detection import DetectionService
from claudewatch.backend.services.history import HistoryService
from claudewatch.backend.services.notifications import NotificationService
from claudewatch.backend.services.onboarding import OnboardingService
from claudewatch.backend.services.summary import SummaryService
from claudewatch.backend.services.updates import UpdateService
from claudewatch.backend.services.usage import UsageService

# Singleton instances — created on first call, reused thereafter
_process_svc: ProcessService | None = None
_session_log_svc: SessionLogService | None = None
_notification_svc: NotificationService | None = None
_onboarding_svc: OnboardingService | None = None
_usage_svc: UsageService | None = None
_summary_svc: SummaryService | None = None
_detection_svc: DetectionService | None = None
_update_svc: UpdateService | None = None
_bookmark_svc: BookmarkService | None = None
_history_svc: HistoryService | None = None


def get_process_service() -> ProcessService:
    global _process_svc  # noqa: PLW0603
    if _process_svc is None:
        _process_svc = ProcessService()
    return _process_svc


def get_session_log_service() -> SessionLogService:
    global _session_log_svc  # noqa: PLW0603
    if _session_log_svc is None:
        _session_log_svc = SessionLogService()
    return _session_log_svc


def get_notification_service() -> NotificationService:
    global _notification_svc  # noqa: PLW0603
    if _notification_svc is None:
        _notification_svc = NotificationService()
    return _notification_svc


def get_onboarding_service() -> OnboardingService:
    global _onboarding_svc  # noqa: PLW0603
    if _onboarding_svc is None:
        _onboarding_svc = OnboardingService(get_notification_service())
    return _onboarding_svc


def get_usage_service() -> UsageService:
    global _usage_svc  # noqa: PLW0603
    if _usage_svc is None:
        _usage_svc = UsageService(get_session_log_service())
    return _usage_svc


def get_summary_service() -> SummaryService:
    global _summary_svc  # noqa: PLW0603
    if _summary_svc is None:
        _summary_svc = SummaryService(get_session_log_service(), get_process_service())
    return _summary_svc


def get_detection_service() -> DetectionService:
    global _detection_svc  # noqa: PLW0603
    if _detection_svc is None:
        _detection_svc = DetectionService(get_process_service(), get_session_log_service())
    return _detection_svc


def get_update_service() -> UpdateService:
    global _update_svc  # noqa: PLW0603
    if _update_svc is None:
        _update_svc = UpdateService()
    return _update_svc


def get_bookmark_service() -> BookmarkService:
    global _bookmark_svc  # noqa: PLW0603
    if _bookmark_svc is None:
        _bookmark_svc = BookmarkService()
    return _bookmark_svc


def get_history_service() -> HistoryService:
    global _history_svc  # noqa: PLW0603
    if _history_svc is None:
        _history_svc = HistoryService()
    return _history_svc
