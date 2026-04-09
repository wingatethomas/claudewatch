"""SummaryService — generate conversation summaries via the Claude CLI.

Persistence is delegated to SummaryRepository. This service owns business
logic (extraction, prompts, parsing) and orchestration (background threads,
queues, failure tracking, concurrency control).
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
from claudewatch.backend.core.process.service import ProcessService
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.summary.repository import SummaryRepository

log = logging.getLogger("claudewatch")

_MAX_CONTEXT_CHARS = 16000
_TIMEOUT_SECONDS = 60
_REFRESH_INTERVAL = 60  # seconds between background refresh cycles
_MAX_FAILURES = 5  # stop retrying after this many consecutive failures

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
    if "present-tense verb phrase" in raw or "max 30 chars" in raw:
        return ("", "")

    lines = raw.strip().splitlines()
    title = ""
    bullets: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("TITLE:"):
            title = stripped[6:].strip()
        elif stripped.startswith("•") or stripped.startswith("-"):
            bullet = stripped.lstrip("•-").strip()
            if bullet:
                bullets.append(f"• {bullet}")

    if not title and bullets:
        title = bullets[0].lstrip("• ").strip()
    elif not title and lines:
        title = lines[0].strip()

    if not bullets:
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.upper().startswith("TITLE:"):
                bullets.append(f"• {stripped}")
                if len(bullets) >= 3:  # noqa: PLR2004
                    break

    if not title and not bullets:
        return ("", "")

    _max_title = 30
    if len(title) > _max_title:
        truncated = title[:_max_title]
        last_space = truncated.rfind(" ")
        if last_space > _max_title // 2:
            truncated = truncated[:last_space]
        title = truncated

    return title, "\n".join(bullets)


class SummaryService(BaseService):
    """Generates and caches conversation summaries via ``claude -p``."""

    def __init__(
        self,
        repository: SummaryRepository,
        session_log_service: SessionLogService,
        process_service: ProcessService,
    ) -> None:
        super().__init__()
        self._repo = repository
        self._session_log_service = session_log_service
        self._process_service = process_service

        # Concurrency control
        self._generating = threading.Lock()  # only 1 claude -p at a time
        self._in_progress: set[str] = set()
        self._in_progress_lock = threading.Lock()

        # Persistent session for summaries — reuse instead of spawning new processes
        self._summary_session_id: str | None = None
        self._session_failures: int = 0
        self._session_failure_threshold = 2

        # Failure tracking: {key: (count, jsonl_mtime_at_failure)}
        self._failures: dict[str, tuple[int, float]] = {}
        self._failures_lock = threading.Lock()

        # Background thread
        self._bg_thread: threading.Thread | None = None
        self._tracked_cwds: set[str] = set()  # cache keys
        self._tracked_lock = threading.Lock()
        self._priority_queue: list[tuple[str, str]] = []  # (cwd, session_id)
        self._priority_lock = threading.Lock()

    # -- Public API (delegates persistence to repository) -------------------

    @staticmethod
    def _cache_key(cwd: str, session_id: str = "") -> str:
        return SummaryRepository._cache_key(cwd, session_id)

    def get_cached(self, cwd: str, session_id: str = "") -> str | None:
        """Return the title (one-liner)."""
        entry = self._repo.get_entry(cwd, session_id)
        if not entry:
            return None
        return entry.title or entry.summary

    def get_cached_title(self, cwd: str, session_id: str = "") -> str | None:
        """Return the short title."""
        return self.get_cached(cwd, session_id)

    def get_cached_summary(self, cwd: str, session_id: str = "") -> str | None:
        """Return the bulleted summary."""
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

    def is_generating(self, cwd: str, session_id: str = "") -> bool:
        """Check if a summary is currently being generated."""
        key = self._cache_key(cwd, session_id)
        with self._in_progress_lock:
            return key in self._in_progress

    def get_status(self, cwd: str, session_id: str = "") -> str:
        """Get the summary status: 'cached', 'generating', 'failed', or 'pending'."""
        key = self._cache_key(cwd, session_id)
        if self._repo.get_entry(cwd, session_id):
            return "cached"
        with self._in_progress_lock:
            if key in self._in_progress:
                return "generating"
        with self._failures_lock:
            fail_entry = self._failures.get(key)
            if fail_entry is not None:
                fail_count = fail_entry[0] if isinstance(fail_entry, tuple) else fail_entry
                if fail_count >= _MAX_FAILURES:
                    return "failed"
        return "pending"

    def generate_and_cache(self, cwd: str, session_id: str = "") -> str:  # noqa: PLR0912
        """Generate a summary via claude -p and persist it."""
        key = self._cache_key(cwd, session_id)
        cached = self.get_cached(cwd, session_id)
        if cached is not None:
            return cached

        with self._failures_lock:
            fail_entry = self._failures.get(key)
            if fail_entry is not None:
                if isinstance(fail_entry, tuple):
                    fail_count, fail_mtime = fail_entry
                else:
                    fail_count, fail_mtime = fail_entry, 0.0
                if fail_count >= _MAX_FAILURES:
                    current_mtime = self._repo.get_jsonl_mtime(cwd)
                    if current_mtime and current_mtime > fail_mtime:
                        self._failures.pop(key, None)
                    else:
                        return ""

        with self._in_progress_lock:
            if key in self._in_progress:
                return ""
            self._in_progress.add(key)

        try:
            if not self._generating.acquire(timeout=1):
                return ""
            try:
                raw = self._call_claude(cwd)
                if raw:
                    title, bullets = _parse_summary_response(raw)
                    self.cache_full(cwd, title, bullets, session_id)
                    with self._failures_lock:
                        self._failures.pop(key, None)
                else:
                    with self._failures_lock:
                        prev = self._failures.get(key)
                        prev_count = prev[0] if isinstance(prev, tuple) else (prev or 0)
                        mtime = self._repo.get_jsonl_mtime(cwd)
                        self._failures[key] = (prev_count + 1, mtime)
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
                self._in_progress.discard(key)

    def invalidate_cache(self, cwd: str, session_id: str = "") -> None:
        """Remove a session from the summary store and reset failure count."""
        key = self._cache_key(cwd, session_id)
        self._repo.invalidate_entry(cwd, session_id)
        with self._failures_lock:
            self._failures.pop(key, None)

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
            try:
                entry = None
                with self._priority_lock:
                    if self._priority_queue:
                        entry = self._priority_queue.pop(0)
                if entry:
                    cwd, sid = entry
                    log.debug("bg_priority: generating summary for %s", cwd)
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
                        log.debug("bg_refresh: regenerating stale summary for %s", cwd)
                        self.generate_and_cache(cwd, sid)
            except Exception:
                log.exception("bg_refresh_loop iteration failed")
                time.sleep(_REFRESH_INTERVAL)

    # -- Business logic (extraction, LLM calls) -----------------------------

    def _extract_conversation_text(self, cwd: str) -> str:  # noqa: PLR0912, PLR0915
        """Extract a structured event timeline from JSONL — token-efficient."""
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

        use_session = self._session_failures < self._session_failure_threshold

        session_id = self._summary_session_id
        if session_id and use_session:
            cmd = [
                claude_path, "-p", _CONVERSATION_PREFIX + conversation,
                "-r", session_id, "--model", model, "--effort", effort,
            ]
            log.debug("summarize: reusing session %s", session_id[:8])
        elif use_session:
            session_id = str(uuid.uuid4())
            cmd = [
                claude_path, "-p", _SYSTEM_PROMPT + _CONVERSATION_PREFIX + conversation,
                "--session-id", session_id, "--model", model, "--effort", effort,
            ]
            log.info("summarize: creating session %s", session_id[:8])
        else:
            cmd = [
                claude_path, "-p", _SYSTEM_PROMPT + _CONVERSATION_PREFIX + conversation,
                "--model", model, "--effort", effort,
            ]
            log.debug("summarize: using non-session fallback")

        result = self._run_claude_process(cmd)
        if result:
            if use_session:
                self._summary_session_id = session_id
                self._session_failures = 0
            return result

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
