from functools import lru_cache

from claudewatch.backend.core.session_log.service import SessionLogService


@lru_cache(maxsize=1)
def get_session_log_service() -> SessionLogService:
    return SessionLogService()
