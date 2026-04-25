"""HistoryService — facade over the history repository for UI consumption."""

import threading

from claudewatch.backend.core.dto import HistoryEntryDTO
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.history import repository as history_repo


class HistoryService(BaseService):
    """Record, list, and remove session history entries as DTOs.

    Holds an in-memory cache of the history list so menu builds (main thread)
    don't trigger JSON file reads. Cache is lazy-loaded on first read and
    invalidated by every mutation.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cache: list[HistoryEntryDTO] | None = None
        self._cache_lock = threading.Lock()

    def record(self, session_id: str, project: str, cwd: str, model: str, host_app: str) -> None:
        """Record a session when it ends."""
        history_repo.record_session(session_id, project, cwd, model, host_app)
        self._invalidate()

    def get_all(self) -> list[HistoryEntryDTO]:
        """Return all history entries as DTOs, newest first."""
        with self._cache_lock:
            if self._cache is None:
                self._cache = history_repo.get_history()
            return list(self._cache)

    def remove(self, cwd: str) -> None:
        """Remove a history entry by CWD."""
        history_repo.remove_history_entry(cwd)
        self._invalidate()

    def warm(self) -> None:
        """Pre-populate the cache. Call from a background thread so the first
        main-thread read of history data doesn't block on disk I/O."""
        with self._cache_lock:
            self._cache = history_repo.get_history()

    def _invalidate(self) -> None:
        with self._cache_lock:
            self._cache = None
