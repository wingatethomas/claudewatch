from functools import lru_cache

from claudewatch.backend.notifications.service import NotificationService


@lru_cache(maxsize=1)
def get_notification_service() -> NotificationService:
    return NotificationService()
