from functools import lru_cache

from claudewatch.backend.notifications.dependencies import get_notification_service
from claudewatch.backend.onboarding.service import OnboardingService


@lru_cache(maxsize=1)
def get_onboarding_service() -> OnboardingService:
    return OnboardingService(get_notification_service())
