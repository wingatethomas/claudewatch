from functools import lru_cache

from claudewatch.backend.core.session_log.dependencies import get_session_log_service
from claudewatch.backend.history.service import HistoryService


@lru_cache(maxsize=1)
def get_history_service() -> HistoryService:
    return HistoryService(get_session_log_service())
