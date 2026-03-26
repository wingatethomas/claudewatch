from functools import lru_cache

from claudewatch.backend.core.features import Facet, Feature, register
from claudewatch.backend.core.settings import get_available_sounds
from claudewatch.backend.notifications.service import NotificationService

register(
    Feature(
        "notifications",
        "Notifications",
        facets=(Facet("sound", "choice", "Glass", "Sound", options=get_available_sounds()),),
    )
)


@lru_cache(maxsize=1)
def get_notification_service() -> NotificationService:
    return NotificationService()
