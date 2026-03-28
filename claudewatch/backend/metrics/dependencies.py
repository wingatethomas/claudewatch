"""Metrics service factory."""

from functools import lru_cache

from claudewatch.backend.core.session_log.dependencies import get_session_log_service
from claudewatch.backend.metrics.service import MetricsService


@lru_cache(maxsize=1)
def get_metrics_service() -> MetricsService:
    return MetricsService(get_session_log_service())
