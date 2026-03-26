from functools import lru_cache

from claudewatch.backend.bookmark.service import BookmarkService
from claudewatch.backend.core.features import Facet, Feature, register

register(
    Feature(
        "bookmarks",
        "Bookmarks",
        facets=(
            Facet(
                "expiry_days",
                "choice",
                "30 days",
                "Expiry",
                options=("Never", "7 days", "14 days", "30 days", "60 days", "90 days"),
            ),
        ),
    )
)


@lru_cache(maxsize=1)
def get_bookmark_service() -> BookmarkService:
    return BookmarkService()
