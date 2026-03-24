from functools import lru_cache

from claudewatch.backend.core.session_log.dependencies import get_session_log_service
from claudewatch.backend.usage.service import UsageService


@lru_cache(maxsize=1)
def get_usage_service() -> UsageService:
    return UsageService(get_session_log_service())
