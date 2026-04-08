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
import uuid

from claudewatch.backend.core import features
from claudewatch.backend.core.paths import SUMMARIES_PATH
from claudewatch.backend.core.process.service import ProcessService
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.summary.models import SummaryEntry

log = logging.getLogger("claudewatch")

_MAX_STORE_ENTRIES = 500
_STORE_MAX_AGE = 30 * 86400  # 30 days
_MAX_CONTEXT_CHARS = 16000
_TIMEOUT_SECONDS = 60
_REFRESH_INTERVAL = 60  # seconds between background refresh cycles
_MAX_FAILURES = 5  # stop retrying after this many consecutive failures per CWD
_STALENESS_SIZE_THRESHOLD = 10240  # 10KB — invalidate if JSONL grew more than this

_SYSTEM_PROMPT = (
    "You are a session summarizer for Claude Code. "
    "You will receive structured event timelines from coding sessions. "
    "Always respond in this exact format — no other text, no explanations:\n"
    "TITLE: <present-tense verb phrase, max 30 chars>\n"
    "• <what was done> (max 50 chars)\n"
    "• <what was done>\n"
    "• <what was done>\n\n"
    "Rules:\n"
    "- Title describes the MOST RECENT activity\n"
    "- 3-6 bullets covering key actions chronologically\n"
    "- Skip: greetings, confirmations, tool approvals, 'waiting for input'\n"
    "- Focus: code changes, files edited, features built, bugs fixed, tests run\n"
    "- If the session has minimal activity, summarize what IS there. Never say 'I don't see' or 'no activity'.\n"
    "- Even a single user message is enough — summarize the topic.\n"
)

_CONVERSATION_PREFIX = "Summarize this session:\n\n"


def _parse_summary_response(raw: str) -> tuple[str, str]:  # noqa: PLR0912
    """Parse the TITLE + bullets format from claude -p output.

    Returns (title, bullets_string). Falls back gracefully if format is unexpected.
    Rejects responses that echo back the prompt.
    """
    # Reject prompt echo-back
    if "present-tense verb phrase" in raw or "max 30 chars" in raw:
        return ("", "")

    lines = raw.strip().splitlines()
    title = ""
    bullets: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Case-insensitive title match
        if stripped.upper().startswith("TITLE:"):
            title = stripped[6:].strip()
        elif stripped.startswith("•") or stripped.startswith("-"):
            bullet = stripped.lstrip("•-").strip()
            if bullet:
                bullets.append(f"• {bullet}")

    # Fallback: if no title but has bullets, use first bullet as title
    if not title and bullets:
        title = bullets[0].lstrip("• ").strip()
    # Fallback: if nothing structured, use first non-empty line
    elif not title and lines:
        title = lines[0].strip()

    # Fallback: if no bullets, use non-title lines as bullets
    if not bullets:
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.upper().startswith("TITLE:"):
                bullets.append(f"• {stripped}")
                if len(bullets) >= 3:  # noqa: PLR2004
                    break

    # Structural validation: must have a title or bullets to be useful
    if not title and not bullets:
        return ("", "")

    # Clamp title at word boundary
    _max_title = 30
    if len(title) > _max_title:
        truncated = title[:_max_title]
        last_space = truncated.rfind(" ")
        if last_space > _max_title // 2:
            truncated = truncated[:last_space]
        title = truncated

    return title, "\n".join(bullets)


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

        # In-memory mirror of the persistent store: CWD -> SummaryEntry
        self._store: dict[str, SummaryEntry] = {}
        self._store_loaded = False
        self._store_lock = threading.Lock()

        # Concurrency control
        self._generating = threading.Lock()  # only 1 claude -p at a time
        self._in_progress: set[str] = set()
        self._in_progress_lock = threading.Lock()

        # Persistent session for summaries — reuse instead of spawning new processes
        self._summary_session_id: str | None = None
        self._session_failures: int = 0
        self._session_failure_threshold = 2  # after this many, fall back to non-session mode

        # Failure tracking: {cwd: (count, jsonl_mtime_at_failure)}
        self._failures: dict[str, tuple[int, float]] = {}
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
        # Prune entries older than 30 days
        cutoff = time.time() - _STORE_MAX_AGE
        before = len(self._store)
        self._store = {k: v for k, v in self._store.items() if v.mtime > cutoff}
        # Cap total entries
        if len(self._store) > _MAX_STORE_ENTRIES:
            sorted_keys = sorted(self._store, key=lambda k: self._store[k].mtime)
            for k in sorted_keys[: len(self._store) - _MAX_STORE_ENTRIES]:
                del self._store[k]
        if len(self._store) < before:
            self._save_store()
        self._store_loaded = True

    def _save_store(self) -> None:
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

    # -- Public API ---------------------------------------------------------

    def _get_entry(self, cwd: str) -> SummaryEntry | None:
        """Return the cached entry if JSONL hasn't changed significantly since generation."""
        with self._store_lock:
            self._load_store()
            entry = self._store.get(cwd)
        if not entry:
            return None
        current_mtime = self._get_jsonl_mtime(cwd)
        if not current_mtime or current_mtime > entry.mtime:
            return None
        # Also check if file grew significantly (new activity without mtime change)
        current_size = self._get_jsonl_size(cwd)
        if current_size and entry.jsonl_size and current_size - entry.jsonl_size > _STALENESS_SIZE_THRESHOLD:
            return None
        return entry

    def get_cached(self, cwd: str) -> str | None:
        """Return the title (one-liner). Backward compatible — used by menu bar."""
        entry = self._get_entry(cwd)
        if not entry:
            return None
        # Support old format (plain "summary" string) and new format ("title" + "summary")
        return entry.title or entry.summary

    def get_cached_title(self, cwd: str) -> str | None:
        """Return the short title (what's happening now)."""
        return self.get_cached(cwd)

    def get_cached_summary(self, cwd: str) -> str | None:
        """Return the bulleted summary of all session actions."""
        entry = self._get_entry(cwd)
        if not entry:
            return None
        return entry.summary

    def cache(self, cwd: str, summary: str) -> None:
        """Persist a summary. Accepts plain string (becomes title) or title+summary."""
        mtime = self._get_jsonl_mtime(cwd) or time.time()
        with self._store_lock:
            self._load_store()
            existing = self._store.get(cwd)
            if existing and existing.summary:
                # Preserve existing summary if only updating title
                self._store[cwd] = SummaryEntry(title=summary, summary=existing.summary, mtime=mtime)
            else:
                self._store[cwd] = SummaryEntry(title=summary, summary="", mtime=mtime)
            self._save_store()

    def cache_full(self, cwd: str, title: str, summary: str) -> None:
        """Persist both title and bulleted summary."""
        mtime = self._get_jsonl_mtime(cwd) or time.time()
        size = self._get_jsonl_size(cwd)
        with self._store_lock:
            self._load_store()
            self._store[cwd] = SummaryEntry(title=title, summary=summary, mtime=mtime, jsonl_size=size)
            self._save_store()

    def clear_all(self) -> None:
        """Delete all cached summaries."""
        with self._store_lock:
            self._store.clear()
            self._save_store()

    def is_generating(self, cwd: str) -> bool:
        """Check if a summary is currently being generated for a CWD."""
        with self._in_progress_lock:
            return cwd in self._in_progress

    def get_status(self, cwd: str) -> str:
        """Get the summary status for a CWD: 'cached', 'generating', 'failed', or 'pending'."""
        if self._get_entry(cwd):
            return "cached"
        if self.is_generating(cwd):
            return "generating"
        with self._failures_lock:
            fail_entry = self._failures.get(cwd)
            if fail_entry is not None:
                fail_count = fail_entry[0] if isinstance(fail_entry, tuple) else fail_entry
                if fail_count >= _MAX_FAILURES:
                    return "failed"
        return "pending"

    def generate_and_cache(self, cwd: str) -> str:  # noqa: PLR0912
        """Generate a summary via claude -p and persist it.

        Skips if already cached and fresh, if another generation is in progress,
        or if this CWD has failed too many times consecutively.
        """
        cached = self.get_cached(cwd)
        if cached is not None:
            return cached

        with self._failures_lock:
            fail_entry = self._failures.get(cwd)
            if fail_entry is not None:
                # Handle both old format (int) and new format (count, mtime)
                if isinstance(fail_entry, tuple):
                    fail_count, fail_mtime = fail_entry
                else:
                    fail_count, fail_mtime = fail_entry, 0.0
                if fail_count >= _MAX_FAILURES:
                    current_mtime = self._get_jsonl_mtime(cwd)
                    if current_mtime and current_mtime > fail_mtime:
                        self._failures.pop(cwd, None)
                    else:
                        return ""

        with self._in_progress_lock:
            if cwd in self._in_progress:
                return ""
            self._in_progress.add(cwd)

        try:
            if not self._generating.acquire(timeout=1):
                return ""
            try:
                raw = self._call_claude(cwd)
                if raw:
                    title, bullets = _parse_summary_response(raw)
                    self.cache_full(cwd, title, bullets)
                    with self._failures_lock:
                        self._failures.pop(cwd, None)
                else:
                    with self._failures_lock:
                        prev = self._failures.get(cwd)
                        prev_count = prev[0] if isinstance(prev, tuple) else (prev or 0)
                        mtime = self._get_jsonl_mtime(cwd)
                        self._failures[cwd] = (prev_count + 1, mtime)
                        count = prev_count + 1
                    if count >= _MAX_FAILURES:
                        log.warning(
                            "summarize: giving up on %s after %d failures",
                            os.path.basename(cwd),
                            count,
                        )
                    title = ""
                return title
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

    def track_session(self, cwd: str, *, urgent: bool = False) -> None:
        """Register a CWD for periodic background summary refresh.

        If no summary exists yet, queues it for generation.
        *urgent* sessions (Attention/Working) are inserted at the front of the queue.
        """
        with self._tracked_lock:
            self._tracked_cwds.add(cwd)
        if self.get_cached(cwd) is None:
            with self._priority_lock:
                if cwd not in self._priority_queue:
                    if urgent:
                        self._priority_queue.insert(0, cwd)
                    else:
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
        if not features.is_enabled("background_summaries"):
            return
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
                log.debug("bg_priority: generating summary for %s", cwd)
                self.generate_and_cache(cwd)
                time.sleep(2)
                continue

            time.sleep(_REFRESH_INTERVAL)
            with self._tracked_lock:
                cwds = list(self._tracked_cwds)
            for cwd in cwds:
                if self.get_cached(cwd) is None:
                    log.debug("bg_refresh: regenerating stale summary for %s", cwd)
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

    def _get_jsonl_size(self, cwd: str) -> int:
        """Get the file size of the most recent JSONL for a CWD."""
        path = self._session_log_service.find_most_recent(cwd)
        if path:
            try:
                return os.path.getsize(path)
            except OSError:
                pass
        return 0

    def _extract_conversation_text(self, cwd: str) -> str:  # noqa: PLR0912, PLR0915
        """Extract a structured event timeline from JSONL — token-efficient.

        Deduplicates consecutive identical tool calls and groups by turn.
        Skips tool_result entries and boilerplate.
        """
        path = self._session_log_service.find_most_recent(cwd)
        if not path:
            return ""

        tail = self._session_log_service.read_tail(path, tail_bytes=200000)
        if not tail:
            return ""

        parts: list[str] = []
        total = 0
        last_tool: str = ""
        last_tool_count: int = 0

        def _flush_tool() -> None:
            nonlocal last_tool, last_tool_count
            if last_tool:
                suffix = f" ({last_tool_count}x)" if last_tool_count > 1 else ""
                parts.append(f"TOOL: {last_tool}{suffix}")
                last_tool = ""
                last_tool_count = 0

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
                _flush_tool()
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    text = content.strip()[:200]
                    parts.append(f"USER: {text}")
                    total += len(text)

            elif dtype == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            key_arg = ""
                            if isinstance(inp, dict):
                                key_arg = str(inp.get("command") or inp.get("file_path") or inp.get("pattern") or "")[
                                    :100
                                ]
                            tool_key = f"{name} → {key_arg}" if key_arg else name

                            # Deduplicate consecutive identical tool calls
                            if tool_key == last_tool:
                                last_tool_count += 1
                            else:
                                _flush_tool()
                                last_tool = tool_key
                                last_tool_count = 1
                            total += 30
                        elif block.get("type") == "text":
                            _flush_tool()
                            text = block.get("text", "").strip()
                            _min_text = 20
                            if text and len(text) > _min_text:
                                parts.append(f"ASSISTANT: {text[:150]}")
                                total += min(len(text), 150)

            if total > _MAX_CONTEXT_CHARS:
                break

        _flush_tool()
        return "\n".join(parts)

    @staticmethod
    def _find_claude() -> str | None:
        """Find the claude CLI, checking common install paths if PATH is limited."""
        found = shutil.which("claude")
        if found:
            return found
        for path in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude", os.path.expanduser("~/.claude/bin/claude")):
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return None

    def _call_claude(self, cwd: str) -> str:
        """Call claude -p to generate a summary. Reuses a persistent session when possible."""
        claude_path = self._find_claude()
        if not claude_path:
            log.warning("summarize: claude CLI not found")
            return ""

        conversation = self._extract_conversation_text(cwd)
        if not conversation:
            return ""

        model = str(features.get_facet("background_summaries", "model") or "haiku")
        effort = str(features.get_facet("background_summaries", "effort") or "low")

        # Use persistent session if available and not failing repeatedly
        use_session = self._session_failures < self._session_failure_threshold

        session_id = self._summary_session_id
        if session_id and use_session:
            # Resume existing session — system prompt already in context
            cmd = [
                claude_path,
                "-p",
                _CONVERSATION_PREFIX + conversation,
                "-r",
                session_id,
                "--model",
                model,
                "--effort",
                effort,
            ]
            log.debug("summarize: reusing session %s", session_id[:8])
        elif use_session:
            # First call — create new session with system prompt
            session_id = str(uuid.uuid4())
            cmd = [
                claude_path,
                "-p",
                _SYSTEM_PROMPT + _CONVERSATION_PREFIX + conversation,
                "--session-id",
                session_id,
                "--model",
                model,
                "--effort",
                effort,
            ]
            log.info("summarize: creating session %s", session_id[:8])
        else:
            # Fallback — no session flags, just plain -p (CLI may not support sessions)
            cmd = [
                claude_path,
                "-p",
                _SYSTEM_PROMPT + _CONVERSATION_PREFIX + conversation,
                "--model",
                model,
                "--effort",
                effort,
            ]
            log.debug("summarize: using non-session fallback")

        result = self._run_claude_process(cmd)
        if result:
            if use_session:
                self._summary_session_id = session_id
                self._session_failures = 0
            return result

        # Failed — reset session so next call creates a fresh one
        if use_session:
            self._session_failures += 1
            if self._session_failures >= self._session_failure_threshold:
                log.warning("summarize: persistent sessions failing, falling back to non-session mode")
        self._summary_session_id = None
        return ""

    def _run_claude_process(self, cmd: list[str]) -> str:
        """Execute a claude subprocess and return stdout. Returns empty string on failure."""
        try:
            proc = subprocess.Popen(
                cmd,
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
