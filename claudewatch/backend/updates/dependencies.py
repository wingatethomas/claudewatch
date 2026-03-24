from functools import lru_cache

from claudewatch.backend.updates.service import UpdateService


@lru_cache(maxsize=1)
def get_update_service() -> UpdateService:
    return UpdateService()
