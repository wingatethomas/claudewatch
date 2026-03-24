"""Service dependency wiring — factory functions for service instantiation."""

from functools import lru_cache

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


@lru_cache(maxsize=1)
def get_process_service() -> ProcessService:
    return ProcessService()


@lru_cache(maxsize=1)
def get_session_log_service() -> SessionLogService:
    return SessionLogService()


@lru_cache(maxsize=1)
def get_notification_service() -> NotificationService:
    return NotificationService()


@lru_cache(maxsize=1)
def get_onboarding_service() -> OnboardingService:
    return OnboardingService(get_notification_service())


@lru_cache(maxsize=1)
def get_usage_service() -> UsageService:
    return UsageService(get_session_log_service())


@lru_cache(maxsize=1)
def get_summary_service() -> SummaryService:
    return SummaryService(get_session_log_service(), get_process_service())


@lru_cache(maxsize=1)
def get_detection_service() -> DetectionService:
    return DetectionService(get_process_service(), get_session_log_service())


@lru_cache(maxsize=1)
def get_update_service() -> UpdateService:
    return UpdateService()


@lru_cache(maxsize=1)
def get_bookmark_service() -> BookmarkService:
    return BookmarkService()


@lru_cache(maxsize=1)
def get_history_service() -> HistoryService:
    return HistoryService()
