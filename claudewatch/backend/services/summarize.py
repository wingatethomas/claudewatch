"""Generate and persist conversation summaries via the Claude CLI.

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

from claudewatch.backend.services.jsonl import find_most_recent_jsonl, read_jsonl_tail

log = logging.getLogger("claudewatch")

_MAX_CONTEXT_CHARS = 8000
_TIMEOUT_SECONDS = 15
_REFRESH_INTERVAL = 60  # seconds between background refresh cycles
_STORE_PATH = os.path.expanduser("~/.claude/claudewatch-summaries.json")

_PROMPT = (
    "Summarize this Claude Code conversation in 3-4 sentences. "
    "Cover: what the user was trying to accomplish, what was done, key files or areas touched, "
    "and the current state (e.g. merged, in progress, blocked). "
    "Do not use markdown. Do not start with 'The user' or 'This conversation'. "
    "Example: 'Debugging auth middleware after session tokens were stored incorrectly. "
    "Fixed token validation in auth.py, added integration tests, updated the migration. "
    "PR #42 is merged to main.'\n\n"
)

# In-memory mirror of the persistent store: CWD → {"summary": str, "mtime": float}
_store: dict[str, dict] = {}
_store_loaded = False
_store_lock = threading.Lock()

# Concurrency control
_generating = threading.Lock()  # only 1 claude -p at a time
_in_progress: set[str] = set()
_in_progress_lock = threading.Lock()

# PIDs of our own claude -p subprocesses (for detection filtering)
_our_pids: set[int] = set()
_our_pids_lock = threading.Lock()

# Background thread
_bg_thread: threading.Thread | None = None
_tracked_cwds: set[str] = set()  # CWDs to periodically refresh
_tracked_lock = threading.Lock()


# ── Persistent store ──────────────────────────────────────────────────


def _load_store() -> None:
    global _store, _store_loaded  # noqa: PLW0603
    if _store_loaded:
        return
    try:
        with open(_STORE_PATH) as f:
            data = json.load(f)
            if isinstance(data, dict):
                _store = data
    except (OSError, json.JSONDecodeError):
        _store = {}
    _store_loaded = True


def _save_store() -> None:
    try:
        with open(_STORE_PATH, "w") as f:
            json.dump(_store, f, indent=2)
    except OSError:
        log.warning("Failed to save summaries to %s", _STORE_PATH)


# ── Public API ────────────────────────────────────────────────────────


def get_cached_summary(cwd: str) -> str | None:
    """Return stored summary if JSONL hasn't changed since generation."""
    with _store_lock:
        _load_store()
        entry = _store.get(cwd)
    if not entry:
        return None
    cached_mtime = entry.get("mtime", 0)
    current_mtime = _get_jsonl_mtime(cwd)
    if current_mtime and current_mtime <= cached_mtime:
        return entry.get("summary", "")
    return None


def cache_summary(cwd: str, summary: str) -> None:
    """Persist a summary keyed to the current JSONL mtime."""
    mtime = _get_jsonl_mtime(cwd) or time.time()
    with _store_lock:
        _load_store()
        _store[cwd] = {"summary": summary, "mtime": mtime}
        _save_store()


def get_our_pids() -> set[int]:
    """Return PIDs of our own claude -p subprocesses (for detection filtering)."""
    with _our_pids_lock:
        return set(_our_pids)


def is_generating(cwd: str) -> bool:
    """Check if a summary is currently being generated for a CWD."""
    with _in_progress_lock:
        return cwd in _in_progress


def generate_and_cache_summary(cwd: str) -> str:
    """Generate a summary via claude -p and persist it.

    Skips if already cached and fresh, or if another generation is in progress.
    """
    cached = get_cached_summary(cwd)
    if cached is not None:
        return cached

    with _in_progress_lock:
        if cwd in _in_progress:
            return ""
        _in_progress.add(cwd)

    try:
        if not _generating.acquire(timeout=1):
            return ""
        try:
            summary = _call_claude(cwd)
            if summary:
                cache_summary(cwd, summary)
            return summary
        finally:
            _generating.release()
    finally:
        with _in_progress_lock:
            _in_progress.discard(cwd)


def invalidate_cache(cwd: str) -> None:
    """Remove a CWD from the summary store."""
    with _store_lock:
        _load_store()
        _store.pop(cwd, None)
        _save_store()


# ── Background refresh ────────────────────────────────────────────────


def track_session(cwd: str) -> None:
    """Register a CWD for periodic background summary refresh."""
    with _tracked_lock:
        _tracked_cwds.add(cwd)
    _ensure_bg_thread()


def untrack_session(cwd: str) -> None:
    """Stop refreshing summaries for a CWD."""
    with _tracked_lock:
        _tracked_cwds.discard(cwd)


def _ensure_bg_thread() -> None:
    global _bg_thread  # noqa: PLW0603
    if _bg_thread is not None and _bg_thread.is_alive():
        return
    _bg_thread = threading.Thread(target=_bg_refresh_loop, daemon=True)
    _bg_thread.start()


def _bg_refresh_loop() -> None:
    """Periodically check tracked sessions and regenerate stale summaries."""
    while True:
        time.sleep(_REFRESH_INTERVAL)
        with _tracked_lock:
            cwds = list(_tracked_cwds)
        for cwd in cwds:
            if get_cached_summary(cwd) is None:
                log.debug("bg_refresh: regenerating summary for %s", cwd)
                generate_and_cache_summary(cwd)


# ── Internal helpers ──────────────────────────────────────────────────


def _get_jsonl_mtime(cwd: str) -> float:
    """Get the modification time of the most recent JSONL for a CWD."""
    path = find_most_recent_jsonl(cwd)
    if path:
        try:
            return os.path.getmtime(path)
        except OSError:
            pass
    return 0.0


def _extract_conversation_text(cwd: str) -> str:  # noqa: PLR0912
    """Extract a condensed conversation from the most recent JSONL."""
    path = find_most_recent_jsonl(cwd)
    if not path:
        return ""

    tail = read_jsonl_tail(path, tail_bytes=50000)
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


def _call_claude(cwd: str) -> str:
    """Call claude -p to generate a summary. Returns empty string on failure."""
    claude_path = shutil.which("claude")
    if not claude_path:
        log.warning("summarize: claude CLI not found")
        return ""

    conversation = _extract_conversation_text(cwd)
    if not conversation:
        return ""

    try:
        proc = subprocess.Popen(
            [claude_path, "-p", _PROMPT + conversation],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with _our_pids_lock:
            _our_pids.add(proc.pid)
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
            with _our_pids_lock:
                _our_pids.discard(proc.pid)
    except OSError as e:
        log.warning("summarize: failed to run claude: %s", e)

    return ""
