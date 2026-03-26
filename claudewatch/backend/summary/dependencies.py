from functools import lru_cache

from claudewatch.backend.core.features import Feature, register
from claudewatch.backend.core.process.dependencies import get_process_service
from claudewatch.backend.core.session_log.dependencies import get_session_log_service
from claudewatch.backend.summary.service import SummaryService

register(Feature("summaries", "Summaries"))


@lru_cache(maxsize=1)
def get_summary_service() -> SummaryService:
    return SummaryService(get_session_log_service(), get_process_service())
