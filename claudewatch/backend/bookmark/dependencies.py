from functools import lru_cache

from claudewatch.backend.bookmark.service import BookmarkService


@lru_cache(maxsize=1)
def get_bookmark_service() -> BookmarkService:
    return BookmarkService()
