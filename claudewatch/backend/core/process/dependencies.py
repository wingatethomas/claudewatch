from functools import lru_cache

from claudewatch.backend.core.process.service import ProcessService


@lru_cache(maxsize=1)
def get_process_service() -> ProcessService:
    return ProcessService()
