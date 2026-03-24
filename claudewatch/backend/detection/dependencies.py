from functools import lru_cache

from claudewatch.backend.core.process.dependencies import get_process_service
from claudewatch.backend.core.session_log.dependencies import get_session_log_service
from claudewatch.backend.detection.service import DetectionService


@lru_cache(maxsize=1)
def get_detection_service() -> DetectionService:
    return DetectionService(get_process_service(), get_session_log_service())
