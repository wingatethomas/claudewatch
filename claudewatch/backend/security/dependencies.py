"""Security service factory and feature registration."""

from functools import lru_cache

from claudewatch.backend.core.features import Facet, FacetType, Feature, FeatureKey, register
from claudewatch.backend.core.session_log.dependencies import get_session_log_service
from claudewatch.backend.notifications.dependencies import get_notification_service
from claudewatch.backend.security.repository import SecurityRepository
from claudewatch.backend.security.service import SecurityService

register(
    Feature(
        key=FeatureKey.SECURITY,
        description="Security Monitoring",
        default_enabled=True,
        facets=(
            Facet(
                name="config_alerts",
                type=FacetType.BOOL,
                default=True,
                description="Config change alerts",
            ),
            Facet(
                name="runtime_alerts",
                type=FacetType.BOOL,
                default=False,
                description="Runtime security alerts",
            ),
            Facet(
                name="check_interval",
                type=FacetType.CHOICE,
                default="30s",
                description="Check interval",
                options=("10s", "30s", "60s", "5m"),
            ),
            Facet(
                name="alert_sound",
                type=FacetType.CHOICE,
                default="Glass",
                description="Alert sound",
                options=("Glass", "Blow", "Funk", "Hero", "Ping", "Pop", "Purr", "Submarine"),
            ),
        ),
    )
)


@lru_cache(maxsize=1)
def get_security_service() -> SecurityService:
    session_log = get_session_log_service()
    return SecurityService(
        repository=SecurityRepository(session_log=session_log),
        notification_service=get_notification_service(),
        session_log_service=session_log,
    )
