from functools import lru_cache

from claudewatch.backend.core.paths import SUMMARIES_PATH
from claudewatch.backend.core.session_log.dependencies import get_session_log_service
from claudewatch.backend.summary.repository import SummaryRepository
from claudewatch.backend.summary.service import SummaryService


@lru_cache(maxsize=1)
def get_summary_service() -> SummaryService:
    session_log = get_session_log_service()
    repo = SummaryRepository(session_log, store_path=SUMMARIES_PATH)
    return SummaryService(repo, session_log)
