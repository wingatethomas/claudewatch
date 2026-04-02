"""Analytics service factory."""

import os
from functools import lru_cache

from claudewatch.backend.analytics.service import AnalyticsService
from claudewatch.backend.core.paths import CLAUDE_PROJECTS_DIR, DATA_DIR


@lru_cache(maxsize=1)
def get_analytics_service() -> AnalyticsService:
    db_path = os.path.join(DATA_DIR, "analytics.db")
    return AnalyticsService(db_path, CLAUDE_PROJECTS_DIR)
