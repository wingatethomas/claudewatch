from functools import lru_cache

from claudewatch.backend.core.features import Facet, FacetType, Feature, FeatureKey, register
from claudewatch.backend.core.settings import get_available_sounds
from claudewatch.backend.notifications.service import NotificationService

register(
    Feature(
        key=FeatureKey.NOTIFICATIONS,
        description="Notifications",
        facets=(
            Facet(
                name="sound",
                type=FacetType.CHOICE,
                default="Glass",
                description="Sound",
                options=get_available_sounds(),
            ),
        ),
    )
)


@lru_cache(maxsize=1)
def get_notification_service() -> NotificationService:
    return NotificationService()
