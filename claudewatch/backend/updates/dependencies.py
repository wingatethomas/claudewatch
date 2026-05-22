from functools import lru_cache

from claudewatch.backend.core.features import Feature, FeatureKey, register
from claudewatch.backend.updates.service import UpdateService

register(Feature(key=FeatureKey.AUTO_UPDATES, description="Auto-update"))


@lru_cache(maxsize=1)
def get_update_service() -> UpdateService:
    return UpdateService()
