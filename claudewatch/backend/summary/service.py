"""SummaryService — surface session recaps and titles from JSONL.

Persistence is delegated to SummaryRepository. This service extracts the
native entries Claude Code writes to its JSONL session logs:

- ``away_summary`` — bulleted recap content emitted on resume
- ``ai-title`` — short generated session title

No subprocess invocation, no LLM calls. If a session has no recap yet, we
return nothing and revisit on the next refresh cycle.
"""

import json
import logging
import os
import threading
import time

from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.schema import FIELD_AI_TITLE, EntryType, Subtype
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.summary.repository import SummaryRepository

log = logging.getLogger("claudewatch")

_REFRESH_INTERVAL = 60  # seconds between background refresh cycles
_MAX_TITLE_LEN = 30
_TAIL_BYTES = 200000


def _truncate_title(title: str) -> str:
    """Truncate a title to _MAX_TITLE_LEN, preferring word boundaries."""
    if len(title) <= _MAX_TITLE_LEN:
        return title
    truncated = title[:_MAX_TITLE_LEN]
    last_space = truncated.rfind(" ")
    if last_space > _MAX_TITLE_LEN // 2:
        truncated = truncated[:last_space]
    return truncated


def _find_last_recap(lines: list[str]) -> str | None:
    """Scan JSONL lines (oldest-first) and return the last away_summary content."""
    recap = None
    for line in lines:
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if d.get("type") == EntryType.SYSTEM and d.get("subtype") == Subtype.AWAY_SUMMARY:
            content = d.get("content", "")
            if isinstance(content, str) and content.strip():
                recap = content.strip()
    return recap


def _find_last_ai_title(lines: list[str]) -> str | None:
    """Scan JSONL lines and return the last ai-title content."""
    title = None
    for line in lines:
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if d.get("type") == EntryType.AI_TITLE:
            value = d.get(FIELD_AI_TITLE, "")
            if isinstance(value, str) and value.strip():
                title = value.strip()
    return title


class SummaryService(BaseService):
    """Reads native recap and title entries from JSONL and caches them."""

    def __init__(
        self,
        repository: SummaryRepository,
        session_log_service: SessionLogService,
    ) -> None:
        super().__init__()
        self._repo = repository
        self._session_log_service = session_log_service

        # No-recap skip cache: {key: jsonl_mtime_at_last_check}
        # Avoids re-scanning JSONLs that have no recap yet and haven't changed.
        self._no_recap_mtimes: dict[str, float] = {}
        self._no_recap_lock = threading.Lock()

        # Background thread state
        self._bg_thread: threading.Thread | None = None
        self._tracked_cwds: set[str] = set()
        self._tracked_lock = threading.Lock()
        self._priority_queue: list[tuple[str, str]] = []
        self._priority_lock = threading.Lock()

    @staticmethod
    def _cache_key(cwd: str, session_id: str = "") -> str:
        return SummaryRepository.cache_key(cwd, session_id)

    # -- Cache access -------------------------------------------------------

    def get_cached(self, cwd: str, session_id: str = "") -> str | None:
        """Return the cached title (falls back to full summary if title is empty)."""
        entry = self._repo.get_entry(cwd, session_id)
        if not entry:
            return None
        return entry.title or entry.summary

    def get_cached_summary(self, cwd: str, session_id: str = "") -> str | None:
        """Return the cached recap content."""
        entry = self._repo.get_entry(cwd, session_id)
        if not entry:
            return None
        return entry.summary

    def cache(self, cwd: str, summary: str, session_id: str = "") -> None:
        """Persist a summary."""
        self._repo.cache(cwd, summary, session_id)

    def cache_full(self, cwd: str, title: str, summary: str, session_id: str = "") -> None:
        """Persist both title and bulleted summary."""
        self._repo.cache_full(cwd, title, summary, session_id)

    def clear_all(self) -> None:
        """Delete all cached summaries."""
        self._repo.clear_all()

    def get_status(self, cwd: str, session_id: str = "") -> str:
        """Get the summary status: 'cached' or 'pending'."""
        if self._repo.get_entry(cwd, session_id):
            return "cached"
        return "pending"

    def invalidate_cache(self, cwd: str, session_id: str = "") -> None:
        """Remove a session from the summary store."""
        key = self._cache_key(cwd, session_id)
        self._repo.invalidate_entry(cwd, session_id)
        with self._no_recap_lock:
            self._no_recap_mtimes.pop(key, None)

    # -- Extraction ---------------------------------------------------------

    def _read_lines(self, path: str) -> list[str] | None:
        """Read JSONL lines from path: tail first, fall back to full file."""
        tail = self._session_log_service.read_tail(path, tail_bytes=_TAIL_BYTES)
        if tail:
            return tail.strip().splitlines()
        try:
            with open(path) as f:
                return f.readlines()
        except OSError:
            return None

    def _extract_recap(self, path: str) -> str | None:
        """Return the most recent away_summary from a JSONL session log."""
        # Tail scan first; full scan as fallback because recaps sit where the
        # pause happened and can scroll past the 200KB tail window for active sessions.
        tail = self._session_log_service.read_tail(path, tail_bytes=_TAIL_BYTES)
        recap = _find_last_recap(tail.strip().splitlines()) if tail else None
        if recap is not None:
            return recap

        try:
            with open(path) as f:
                lines = f.readlines()
        except OSError:
            return None
        return _find_last_recap(lines)

    def _extract_ai_title(self, path: str) -> str | None:
        """Extract Claude Code's native ai-title entry from a JSONL session log."""
        try:
            with open(path) as f:
                lines = f.readlines()
        except OSError:
            return None
        return _find_last_ai_title(lines)

    def generate_and_cache(self, cwd: str, session_id: str = "") -> str:
        """Extract recap+title from the session's own JSONL and persist.

        Returns the title (or empty). Reading the session's own file matters:
        with shared-CWD setups the most-recent JSONL usually belongs to a
        sibling session, and its recap would be cached for everyone.
        """
        key = self._cache_key(cwd, session_id)
        cached = self.get_cached(cwd, session_id)
        if cached is not None:
            return cached

        path = self._session_log_service.resolve_jsonl(cwd, session_id)
        if not path:
            return ""

        # Skip if we already checked and found no recap, and the JSONL hasn't changed.
        try:
            current_mtime = os.path.getmtime(path)
        except OSError:
            current_mtime = 0.0
        with self._no_recap_lock:
            last_check = self._no_recap_mtimes.get(key)
            if last_check is not None and current_mtime and last_check == current_mtime:
                return ""

        recap = self._extract_recap(path)
        if recap is None:
            with self._no_recap_lock:
                self._no_recap_mtimes[key] = current_mtime
            return ""

        title = _truncate_title(self._extract_ai_title(path) or recap)
        self.cache_full(cwd, title, recap, session_id)
        log.debug("summarize: cached recap for %s", os.path.basename(cwd))
        return title

    # -- Background refresh -------------------------------------------------

    def track_session(self, cwd: str, *, urgent: bool = False, session_id: str = "") -> None:
        """Register a session for periodic background summary refresh."""
        key = self._cache_key(cwd, session_id)
        with self._tracked_lock:
            self._tracked_cwds.add(key)
        if self.get_cached(cwd, session_id) is None:
            with self._priority_lock:
                entry = (cwd, session_id)
                if entry not in self._priority_queue:
                    if urgent:
                        self._priority_queue.insert(0, entry)
                    else:
                        self._priority_queue.append(entry)
        self._ensure_bg_thread()

    def pending_summary_count(self) -> int:
        """Return the number of sessions queued for summary extraction."""
        with self._priority_lock:
            return len(self._priority_queue)

    def untrack_session(self, cwd: str) -> None:
        """Stop refreshing summaries for a CWD."""
        with self._tracked_lock:
            self._tracked_cwds.discard(cwd)

    def _ensure_bg_thread(self) -> None:
        if self._bg_thread is not None and self._bg_thread.is_alive():
            return
        self._bg_thread = threading.Thread(target=self._bg_refresh_loop, daemon=True)
        self._bg_thread.start()

    def _bg_refresh_loop(self) -> None:
        """Process priority queue first, then periodically refresh stale summaries."""
        while True:
            try:
                entry = None
                with self._priority_lock:
                    if self._priority_queue:
                        entry = self._priority_queue.pop(0)
                if entry:
                    cwd, sid = entry
                    log.debug("bg_priority: extracting summary for %s", cwd)
                    self.generate_and_cache(cwd, sid)
                    time.sleep(2)
                    continue

                time.sleep(_REFRESH_INTERVAL)
                with self._tracked_lock:
                    keys = list(self._tracked_cwds)
                for key in keys:
                    if "::" in key:
                        cwd, sid = key.split("::", 1)
                    else:
                        cwd, sid = key, ""
                    if self.get_cached(cwd, sid) is None:
                        log.debug("bg_refresh: re-extracting for %s", cwd)
                        self.generate_and_cache(cwd, sid)
            except Exception:
                log.exception("bg_refresh_loop iteration failed")
                time.sleep(_REFRESH_INTERVAL)
