from functools import lru_cache

from claudewatch.backend.core.features import Facet, FacetType, Feature, register
from claudewatch.backend.core.paths import SUMMARIES_PATH
from claudewatch.backend.core.process.dependencies import get_process_service
from claudewatch.backend.core.session_log.dependencies import get_session_log_service
from claudewatch.backend.summary.repository import SummaryRepository
from claudewatch.backend.summary.service import SummaryService

register(
    Feature(
        key="background_summaries",
        description="Background summaries",
        facets=(
            Facet(
                name="model",
                type=FacetType.CHOICE,
                default="haiku",
                description="Model",
                options=("haiku", "sonnet", "opus"),
            ),
            Facet(
                name="effort",
                type=FacetType.CHOICE,
                default="low",
                description="Effort",
                options=("low", "medium", "high"),
            ),
        ),
    )
)


@lru_cache(maxsize=1)
def get_summary_service() -> SummaryService:
    session_log = get_session_log_service()
    repo = SummaryRepository(session_log, store_path=SUMMARIES_PATH)
    return SummaryService(repo, session_log, get_process_service())
