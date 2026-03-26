"""SummaryService — generate and persist conversation summaries via the Claude CLI.

Summaries are stored in ~/.claude/claudewatch-summaries.json keyed by CWD.
A background thread periodically refreshes stale summaries (when the JSONL
has changed since the last generation). Max 1 concurrent claude -p call.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time

from claudewatch.backend.core import features
from claudewatch.backend.core.paths import SUMMARIES_PATH
from claudewatch.backend.core.process.service import ProcessService
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.service import SessionLogService

log = logging.getLogger("claudewatch")

_MAX_CONTEXT_CHARS = 8000
_TIMEOUT_SECONDS = 45
_REFRESH_INTERVAL = 60  # seconds between background refresh cycles
_MAX_FAILURES = 3  # stop retrying after this many consecutive failures per CWD

_PROMPT = (
    "Summarize in under 50 characters. Action verb, no fluff. "
    "Examples: 'Fix auth token storage' / 'Add CI coverage' / 'Refactor prefs UI'\n\n"
)


class SummaryService(BaseService):
    """Generates and caches conversation summaries via ``claude -p``.

    Dependencies are injected via constructor. All module-level state from
    the old ``summarize.py`` is now instance state.
    """

    def __init__(
        self,
        session_log_service: SessionLogService,
        process_service: ProcessService,
        *,
        store_path: str = SUMMARIES_PATH,
    ) -> None:
        super().__init__()
        self._session_log_service = session_log_service
        self._process_service = process_service
        self._store_path = store_path

        # In-memory mirror of the persistent store: CWD -> {"summary": str, "mtime": float}
        self._store: dict[str, dict] = {}
        self._store_loaded = False
        self._store_lock = threading.Lock()

        # Concurrency control
        self._generating = threading.Lock()  # only 1 claude -p at a time
        self._in_progress: set[str] = set()
        self._in_progress_lock = threading.Lock()

        # Failure tracking
        self._failures: dict[str, int] = {}
        self._failures_lock = threading.Lock()

        # Background thread
        self._bg_thread: threading.Thread | None = None
        self._tracked_cwds: set[str] = set()
        self._tracked_lock = threading.Lock()
        self._priority_queue: list[str] = []
        self._priority_lock = threading.Lock()

    # -- Persistent store ---------------------------------------------------

    def _load_store(self) -> None:
        if self._store_loaded:
            return
        try:
            with open(self._store_path) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._store = data
        except (OSError, json.JSONDecodeError):
            self._store = {}
        self._store_loaded = True

    def _save_store(self) -> None:
        try:
            with open(self._store_path, "w") as f:
                json.dump(self._store, f, indent=2)
        except OSError:
            log.warning("Failed to save summaries to %s", self._store_path)

    # -- Public API ---------------------------------------------------------

    def get_cached(self, cwd: str) -> str | None:
        """Return stored summary if JSONL hasn't changed since generation."""
        with self._store_lock:
            self._load_store()
            entry = self._store.get(cwd)
        if not entry:
            return None
        cached_mtime = entry.get("mtime", 0)
        current_mtime = self._get_jsonl_mtime(cwd)
        if current_mtime and current_mtime <= cached_mtime:
            return entry.get("summary", "")
        return None

    def cache(self, cwd: str, summary: str) -> None:
        """Persist a summary keyed to the current JSONL mtime."""
        mtime = self._get_jsonl_mtime(cwd) or time.time()
        with self._store_lock:
            self._load_store()
            self._store[cwd] = {"summary": summary, "mtime": mtime}
            self._save_store()

    def is_generating(self, cwd: str) -> bool:
        """Check if a summary is currently being generated for a CWD."""
        with self._in_progress_lock:
            return cwd in self._in_progress

    def generate_and_cache(self, cwd: str) -> str:
        """Generate a summary via claude -p and persist it.

        Skips if already cached and fresh, if another generation is in progress,
        or if this CWD has failed too many times consecutively.
        """
        if not features.is_enabled("summaries"):
            return ""

        cached = self.get_cached(cwd)
        if cached is not None:
            return cached

        with self._failures_lock:
            if self._failures.get(cwd, 0) >= _MAX_FAILURES:
                return ""

        with self._in_progress_lock:
            if cwd in self._in_progress:
                return ""
            self._in_progress.add(cwd)

        try:
            if not self._generating.acquire(timeout=1):
                return ""
            try:
                summary = self._call_claude(cwd)
                if summary:
                    self.cache(cwd, summary)
                    with self._failures_lock:
                        self._failures.pop(cwd, None)
                else:
                    with self._failures_lock:
                        self._failures[cwd] = self._failures.get(cwd, 0) + 1
                        count = self._failures[cwd]
                    if count >= _MAX_FAILURES:
                        log.warning(
                            "summarize: giving up on %s after %d failures",
                            os.path.basename(cwd),
                            count,
                        )
                return summary
            finally:
                self._generating.release()
        finally:
            with self._in_progress_lock:
                self._in_progress.discard(cwd)

    def invalidate_cache(self, cwd: str) -> None:
        """Remove a CWD from the summary store and reset failure count."""
        with self._store_lock:
            self._load_store()
            self._store.pop(cwd, None)
            self._save_store()
        with self._failures_lock:
            self._failures.pop(cwd, None)

    # -- Background refresh -------------------------------------------------

    def track_session(self, cwd: str) -> None:
        """Register a CWD for periodic background summary refresh.

        If no summary exists yet, queues it for immediate generation.
        """
        with self._tracked_lock:
            self._tracked_cwds.add(cwd)
        if self.get_cached(cwd) is None:
            with self._priority_lock:
                if cwd not in self._priority_queue:
                    self._priority_queue.append(cwd)
        self._ensure_bg_thread()

    def pending_summary_count(self) -> int:
        """Return the number of sessions queued for summary generation."""
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
            cwd = None
            with self._priority_lock:
                if self._priority_queue:
                    cwd = self._priority_queue.pop(0)
            if cwd:
                if self.get_cached(cwd) is None:
                    log.debug("bg_priority: generating summary for %s", cwd)
                    self.generate_and_cache(cwd)
                time.sleep(2)
                continue

            time.sleep(_REFRESH_INTERVAL)
            with self._tracked_lock:
                cwds = list(self._tracked_cwds)
            for cwd in cwds:
                if self.get_cached(cwd) is None:
                    log.debug("bg_refresh: regenerating summary for %s", cwd)
                    self.generate_and_cache(cwd)

    # -- Internal helpers ---------------------------------------------------

    def _get_jsonl_mtime(self, cwd: str) -> float:
        """Get the modification time of the most recent JSONL for a CWD."""
        path = self._session_log_service.find_most_recent(cwd)
        if path:
            try:
                return os.path.getmtime(path)
            except OSError:
                pass
        return 0.0

    def _extract_conversation_text(self, cwd: str) -> str:  # noqa: PLR0912
        """Extract a condensed conversation from the most recent JSONL."""
        path = self._session_log_service.find_most_recent(cwd)
        if not path:
            return ""

        tail = self._session_log_service.read_tail(path, tail_bytes=50000)
        if not tail:
            return ""

        parts: list[str] = []
        total = 0
        for line in tail.strip().splitlines():
            try:
                d = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            dtype = d.get("type", "")
            msg = d.get("message", {})
            if not isinstance(msg, dict):
                continue

            if dtype == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    text = f"User: {content.strip()}"
                    parts.append(text)
                    total += len(text)

            elif dtype == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "").strip()
                            if text:
                                parts.append(f"Assistant: {text}")
                                total += len(text)

            if total > _MAX_CONTEXT_CHARS:
                break

        return "\n".join(parts)

    def _call_claude(self, cwd: str) -> str:
        """Call claude -p to generate a summary. Returns empty string on failure."""
        claude_path = shutil.which("claude")
        if not claude_path:
            log.warning("summarize: claude CLI not found")
            return ""

        conversation = self._extract_conversation_text(cwd)
        if not conversation:
            return ""

        try:
            proc = subprocess.Popen(
                [claude_path, "-p", _PROMPT + conversation],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._process_service.register_child(proc.pid)
            try:
                stdout, _ = proc.communicate(timeout=_TIMEOUT_SECONDS)
                if proc.returncode == 0 and stdout.strip():
                    return stdout.strip()
                log.warning("summarize: claude returned %d", proc.returncode)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                log.warning("summarize: claude timed out after %ds", _TIMEOUT_SECONDS)
            finally:
                self._process_service.unregister_child(proc.pid)
        except OSError as e:
            log.warning("summarize: failed to run claude: %s", e)

        return ""
