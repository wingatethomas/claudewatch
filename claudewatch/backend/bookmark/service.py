"""BookmarkService — facade over the bookmarks repository for UI consumption."""

import threading

from claudewatch.backend.bookmark import repository as bookmarks_repo
from claudewatch.backend.core.dto import BookmarkDTO
from claudewatch.backend.core.service import BaseService


class BookmarkService(BaseService):
    """Bookmark/unbookmark sessions and return DTOs for the UI layer.

    Holds an in-memory cache of the bookmark list so menu builds (main thread)
    don't trigger JSON file reads. Cache is lazy-loaded on first read and
    invalidated by every mutation.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cache: list[BookmarkDTO] | None = None
        self._cache_lock = threading.Lock()

    def add(self, session_id: str, project: str, cwd: str, note: str) -> None:
        """Bookmark a session with a note. Updates if already bookmarked."""
        bookmarks_repo.add_bookmark(session_id, project, cwd, note)
        self._invalidate()

    def remove(self, session_id: str, cwd: str = "") -> None:
        """Remove a bookmark by session id (CWD fallback for legacy entries)."""
        bookmarks_repo.remove_bookmark(session_id, cwd)
        self._invalidate()

    def is_bookmarked(self, session_id: str, cwd: str) -> bool:
        """True if this session is bookmarked.

        Bookmarks with a session id match on it; legacy entries without one
        match by CWD.
        """
        for b in self.get_all():
            if b.session_id:
                if session_id and b.session_id == session_id:
                    return True
            elif b.cwd == cwd:
                return True
        return False

    def get_all(self) -> list[BookmarkDTO]:
        """Return all bookmarked sessions as DTOs."""
        with self._cache_lock:
            if self._cache is None:
                self._cache = bookmarks_repo.get_bookmarks()
            return list(self._cache)

    def get_bookmarked_cwds(self) -> set[str]:
        """Return the set of CWDs that are currently bookmarked."""
        return {b.cwd for b in self.get_all()}

    def clear_all(self) -> None:
        """Delete all bookmarks."""
        bookmarks_repo.clear_all_bookmarks()
        self._invalidate()

    def warm(self) -> None:
        """Pre-populate the cache. Call from a background thread so the first
        main-thread read of bookmark data doesn't block on disk I/O."""
        with self._cache_lock:
            self._cache = bookmarks_repo.get_bookmarks()

    def _invalidate(self) -> None:
        with self._cache_lock:
            self._cache = None
