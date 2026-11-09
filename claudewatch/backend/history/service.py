"""HistoryService — facade over the history repository for UI consumption."""

import threading
from datetime import UTC, datetime, timedelta

from claudewatch.backend.core.dto import HistoryEntryDTO
from claudewatch.backend.core.models import JUST_FINISHED_WINDOW
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.schema import PermissionMode
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.history import repository as history_repo


class HistoryService(BaseService):
    """Record, list, and remove session history entries as DTOs.

    Holds an in-memory cache of the history list so menu builds (main thread)
    don't trigger JSON file reads. Cache is lazy-loaded on first read and
    invalidated by every mutation.
    """

    def __init__(self, session_log_service: SessionLogService | None = None) -> None:
        super().__init__()
        self._session_log_service = session_log_service or SessionLogService()
        self._cache: list[HistoryEntryDTO] | None = None
        self._cache_lock = threading.Lock()

    def logs_exist(self, cwd: str, session_id: str = "") -> bool:
        """True if the session's JSONL (or any log for the CWD) is still on disk.

        Entries whose logs are gone (deleted worktrees, moved projects) can't
        show a model, tokens, or summary — the UI dims them as stale.
        """
        return self._session_log_service.resolve_jsonl(cwd, session_id) is not None

    def remove_stale(self) -> int:
        """Remove entries whose session logs no longer exist. Returns count removed."""
        stale = [e for e in self.get_all() if not self.logs_exist(e.cwd, e.session_id)]
        for entry in stale:
            history_repo.remove_history_entry(entry.session_id, entry.cwd)
        if stale:
            self._invalidate()
        return len(stale)

    def record(  # noqa: PLR0913
        self,
        session_id: str,
        project: str,
        cwd: str,
        model: str,
        host_app: str,
        permission_mode: str = "",
        ended_at: str = "",
    ) -> None:
        """Record a session when it ends."""
        history_repo.record_session(session_id, project, cwd, model, host_app, permission_mode, ended_at)
        self._invalidate()

    def backfill_recent(self, window_seconds: float = JUST_FINISHED_WINDOW) -> None:
        """Pick up sessions that ended while ClaudeWatch wasn't running."""
        if history_repo.backfill_recent(window_seconds):
            self._invalidate()

    def recently_finished(self, now: datetime | None = None) -> list[HistoryEntryDTO]:
        """Ended auto-mode sessions within the just-finished window, newest first."""
        current = now or datetime.now(tz=UTC)
        cutoff = current - timedelta(seconds=JUST_FINISHED_WINDOW)
        finished: list[HistoryEntryDTO] = []
        for entry in self.get_all():
            if entry.permission_mode != PermissionMode.AUTO or not entry.session_id:
                continue
            try:
                ended = datetime.fromisoformat(entry.ended_at)
            except (ValueError, TypeError):
                continue
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=UTC)
            if ended >= cutoff:
                finished.append(entry)
        return finished

    def get_all(self) -> list[HistoryEntryDTO]:
        """Return all history entries as DTOs, newest first."""
        with self._cache_lock:
            if self._cache is None:
                self._cache = history_repo.get_history()
            return list(self._cache)

    def remove(self, session_id: str, cwd: str = "") -> None:
        """Remove a history entry by session id (CWD match for legacy entries without one)."""
        history_repo.remove_history_entry(session_id, cwd)
        self._invalidate()

    def warm(self) -> None:
        """Pre-populate the cache. Call from a background thread so the first
        main-thread read of history data doesn't block on disk I/O."""
        with self._cache_lock:
            self._cache = history_repo.get_history()

    def _invalidate(self) -> None:
        with self._cache_lock:
            self._cache = None
