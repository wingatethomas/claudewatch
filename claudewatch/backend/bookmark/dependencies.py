from functools import lru_cache

from claudewatch.backend.bookmark.service import BookmarkService
from claudewatch.backend.core.features import Facet, FacetType, Feature, register

register(
    Feature(
        key="bookmarks",
        description="Bookmarks",
        facets=(
            Facet(
                name="expiry_days",
                type=FacetType.CHOICE,
                default="30 days",
                description="Expiry",
                options=("Never", "7 days", "14 days", "30 days", "60 days", "90 days"),
            ),
        ),
    )
)


@lru_cache(maxsize=1)
def get_bookmark_service() -> BookmarkService:
    return BookmarkService()
