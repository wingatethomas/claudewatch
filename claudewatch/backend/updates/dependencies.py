from functools import lru_cache

from claudewatch.backend.core.features import Feature, register
from claudewatch.backend.updates.service import UpdateService

register(Feature(key="auto_updates", description="Auto-update"))


@lru_cache(maxsize=1)
def get_update_service() -> UpdateService:
    return UpdateService()
