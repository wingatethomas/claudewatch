"""BookmarkService — facade over the bookmarks repository for UI consumption."""

from claudewatch.backend.bookmark import repository as bookmarks_repo
from claudewatch.backend.core.dto import BookmarkDTO
from claudewatch.backend.core.service import BaseService


class BookmarkService(BaseService):
    """Bookmark/unbookmark sessions and return DTOs for the UI layer."""

    def add(self, session_id: str, project: str, cwd: str, note: str) -> None:
        """Bookmark a session with a note. Updates if already bookmarked."""
        bookmarks_repo.add_bookmark(session_id, project, cwd, note)

    def remove(self, cwd: str) -> None:
        """Remove a bookmark by CWD."""
        bookmarks_repo.remove_bookmark(cwd)

    def get_all(self) -> list[BookmarkDTO]:
        """Return all bookmarked sessions as DTOs."""
        return bookmarks_repo.get_bookmarks()

    def get_bookmarked_cwds(self) -> set[str]:
        """Return the set of CWDs that are currently bookmarked."""
        return bookmarks_repo.get_bookmarked_cwds()

    def clear_all(self) -> None:
        """Delete all bookmarks."""
        bookmarks_repo._save([])
