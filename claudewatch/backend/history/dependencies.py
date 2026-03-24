from functools import lru_cache

from claudewatch.backend.history.service import HistoryService


@lru_cache(maxsize=1)
def get_history_service() -> HistoryService:
    return HistoryService()
