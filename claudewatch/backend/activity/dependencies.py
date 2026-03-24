from functools import lru_cache

from claudewatch.backend.activity.service import ActivityService
from claudewatch.backend.core.session_log.dependencies import get_session_log_service


@lru_cache(maxsize=1)
def get_activity_service() -> ActivityService:
    return ActivityService(get_session_log_service())
