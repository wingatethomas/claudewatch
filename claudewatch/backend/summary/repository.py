"""Summary repository — persistent store for cached conversation summaries."""

from __future__ import annotations

import json
import logging
import os
import threading
import time

from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.summary.models import SummaryEntry

log = logging.getLogger("claudewatch")

_MAX_STORE_ENTRIES = 500
_STORE_MAX_AGE = 30 * 86400  # 30 days
_STALENESS_SIZE_THRESHOLD = 10240  # 10KB — invalidate if JSONL grew more than this


class SummaryRepository:
    """JSON file store for cached summaries, keyed by CWD."""

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
        tmp = self._store_path + ".tmp"
        try:
            serialized = {
                k: {"title": v.title, "summary": v.summary, "mtime": v.mtime, "jsonl_size": v.jsonl_size}
                for k, v in self._store.items()
            }
            with open(tmp, "w") as f:
                json.dump(serialized, f, indent=2)
            os.replace(tmp, self._store_path)
        except OSError:
            log.warning("Failed to save summaries to %s", self._store_path)

    # -- Entry access -------------------------------------------------------

    def get_entry(self, cwd: str) -> SummaryEntry | None:
        """Return the cached entry if JSONL hasn't changed significantly since generation."""
        with self._store_lock:
            self.load_store()
            entry = self._store.get(cwd)
        if not entry:
            return None
        current_mtime = self.get_jsonl_mtime(cwd)
        if not current_mtime or current_mtime > entry.mtime:
            return None
        current_size = self.get_jsonl_size(cwd)
        if current_size and entry.jsonl_size and current_size - entry.jsonl_size > _STALENESS_SIZE_THRESHOLD:
            return None
        return entry

    def cache(self, cwd: str, summary: str) -> None:
        """Persist a summary string as the title."""
        mtime = self.get_jsonl_mtime(cwd) or time.time()
        with self._store_lock:
            self.load_store()
            existing = self._store.get(cwd)
            if existing and existing.summary:
                self._store[cwd] = SummaryEntry(title=summary, summary=existing.summary, mtime=mtime)
            else:
                self._store[cwd] = SummaryEntry(title=summary, summary="", mtime=mtime)
            self._save_store()

    def cache_full(self, cwd: str, title: str, summary: str) -> None:
        """Persist both title and bulleted summary."""
        mtime = self.get_jsonl_mtime(cwd) or time.time()
        size = self.get_jsonl_size(cwd)
        with self._store_lock:
            self.load_store()
            self._store[cwd] = SummaryEntry(title=title, summary=summary, mtime=mtime, jsonl_size=size)
            self._save_store()

    def clear_all(self) -> None:
        """Delete all cached summaries."""
        with self._store_lock:
            self._store.clear()
            self._save_store()

    def invalidate_entry(self, cwd: str) -> None:
        """Remove a single entry from the store."""
        with self._store_lock:
            self.load_store()
            self._store.pop(cwd, None)
            self._save_store()

    # -- JSONL metadata -----------------------------------------------------

    def get_jsonl_mtime(self, cwd: str) -> float:
        """Get the modification time of the most recent JSONL for a CWD."""
        path = self._session_log_service.find_most_recent(cwd)
        if path:
            try:
                return os.path.getmtime(path)
            except OSError:
                pass
        return 0.0

    def get_jsonl_size(self, cwd: str) -> int:
        """Get the file size of the most recent JSONL for a CWD."""
        path = self._session_log_service.find_most_recent(cwd)
        if path:
            try:
                return os.path.getsize(path)
            except OSError:
                pass
        return 0
