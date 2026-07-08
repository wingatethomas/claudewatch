"""Summary repository — persistent store for cached conversation summaries."""

from __future__ import annotations

import json
import logging
import os
import threading
import time

from claudewatch.backend.core.helpers import atomic_json_write
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.summary.models import SummaryEntry

log = logging.getLogger("claudewatch")

_MAX_STORE_ENTRIES = 500
_STORE_MAX_AGE = 30 * 86400  # 30 days
_STALENESS_SIZE_THRESHOLD = 10240  # 10KB — invalidate if JSONL grew more than this


class SummaryRepository:
    """JSON file store for cached summaries, keyed by CWD (or CWD::session_id)."""

    def __init__(self, session_log_service: SessionLogService, *, store_path: str) -> None:
        self._session_log_service = session_log_service
        self._store_path = store_path
        self._store: dict[str, SummaryEntry] = {}
        self._store_loaded = False
        self._store_lock = threading.Lock()

    # -- Store I/O ----------------------------------------------------------

    def load_store(self) -> None:
        """Load the store from disk. Prunes old and excess entries."""
        if self._store_loaded:
            return
        try:
            with open(self._store_path) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._store = {
                        k: SummaryEntry(
                            title=v.get("title", ""),
                            summary=v.get("summary", ""),
                            mtime=v.get("mtime", 0),
                            jsonl_size=v.get("jsonl_size", 0),
                        )
                        for k, v in data.items()
                        if isinstance(v, dict)
                    }
        except (OSError, json.JSONDecodeError):
            self._store = {}
        cutoff = time.time() - _STORE_MAX_AGE
        before = len(self._store)
        self._store = {k: v for k, v in self._store.items() if v.mtime > cutoff}
        if len(self._store) > _MAX_STORE_ENTRIES:
            sorted_keys = sorted(self._store, key=lambda k: self._store[k].mtime)
            for k in sorted_keys[: len(self._store) - _MAX_STORE_ENTRIES]:
                del self._store[k]
        if len(self._store) < before:
            self._save_store()
        self._store_loaded = True

    def _save_store(self) -> None:
        """Atomically write the store to disk."""
        serialized = {
            k: {"title": v.title, "summary": v.summary, "mtime": v.mtime, "jsonl_size": v.jsonl_size}
            for k, v in self._store.items()
        }
        try:
            atomic_json_write(self._store_path, serialized)
        except OSError:
            log.warning("Failed to save summaries to %s", self._store_path)

    # -- Entry access -------------------------------------------------------

    @staticmethod
    def cache_key(cwd: str, session_id: str = "") -> str:
        """Build a unique cache key."""
        return f"{cwd}::{session_id}" if session_id else cwd

    def get_entry(self, cwd: str, session_id: str = "") -> SummaryEntry | None:
        """Return the cached entry unless the session's own JSONL grew significantly.

        Staleness is judged against the session's own file, not the CWD's
        most-recent one — a sibling session writing must not invalidate this
        entry. Plain mtime updates don't invalidate either (active sessions
        write constantly); only >10KB growth or a missing file does.
        """
        key = self.cache_key(cwd, session_id)
        with self._store_lock:
            self.load_store()
            entry = self._store.get(key)
        if not entry:
            return None
        if not self.get_jsonl_mtime(cwd, session_id):
            return None
        current_size = self.get_jsonl_size(cwd, session_id)
        if current_size and entry.jsonl_size:
            if current_size - entry.jsonl_size > _STALENESS_SIZE_THRESHOLD:
                return None
            # JSONLs only append — a recorded size larger than the file means
            # the entry was generated from a different (sibling) file.
            if entry.jsonl_size > current_size:
                return None
        return entry

    def cache(self, cwd: str, summary: str, session_id: str = "") -> None:
        """Persist a summary string as the title."""
        key = self.cache_key(cwd, session_id)
        mtime = self.get_jsonl_mtime(cwd, session_id) or time.time()
        with self._store_lock:
            self.load_store()
            existing = self._store.get(key)
            if existing and existing.summary:
                self._store[key] = SummaryEntry(title=summary, summary=existing.summary, mtime=mtime)
            else:
                self._store[key] = SummaryEntry(title=summary, summary="", mtime=mtime)
            self._save_store()

    def cache_full(self, cwd: str, title: str, summary: str, session_id: str = "") -> None:
        """Persist both title and bulleted summary."""
        key = self.cache_key(cwd, session_id)
        mtime = self.get_jsonl_mtime(cwd, session_id) or time.time()
        size = self.get_jsonl_size(cwd, session_id)
        with self._store_lock:
            self.load_store()
            self._store[key] = SummaryEntry(title=title, summary=summary, mtime=mtime, jsonl_size=size)
            self._save_store()

    def clear_all(self) -> None:
        """Delete all cached summaries."""
        with self._store_lock:
            self._store.clear()
            self._save_store()

    def invalidate_entry(self, cwd: str, session_id: str = "") -> None:
        """Remove a single entry from the store."""
        key = self.cache_key(cwd, session_id)
        with self._store_lock:
            self.load_store()
            self._store.pop(key, None)
            self._save_store()

    # -- JSONL metadata -----------------------------------------------------

    def get_jsonl_mtime(self, cwd: str, session_id: str = "") -> float:
        """Modification time of the session's JSONL (most recent when no session_id)."""
        path = self._session_log_service.resolve_jsonl(cwd, session_id)
        if path:
            try:
                return os.path.getmtime(path)
            except OSError:
                pass
        return 0.0

    def get_jsonl_size(self, cwd: str, session_id: str = "") -> int:
        """File size of the session's JSONL (most recent when no session_id)."""
        path = self._session_log_service.resolve_jsonl(cwd, session_id)
        if path:
            try:
                return os.path.getsize(path)
            except OSError:
                pass
        return 0
