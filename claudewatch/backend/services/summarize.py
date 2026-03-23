"""Generate conversation summaries via the Claude CLI."""

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
_MAX_CONCURRENT = 2  # max simultaneous claude -p calls

# CWD → (summary, jsonl_mtime) — only regenerate when JSONL changes
_summary_cache: dict[str, tuple[str, float]] = {}
_semaphore = threading.Semaphore(_MAX_CONCURRENT)
_in_progress: set[str] = set()  # CWDs currently being summarized
_in_progress_lock = threading.Lock()
_PROMPT = (
    "Summarize this Claude Code conversation in 3-4 sentences. "
    "Cover: what the user was trying to accomplish, what was done, key files or areas touched, "
    "and the current state (e.g. merged, in progress, blocked). "
    "Do not use markdown. Do not start with 'The user' or 'This conversation'. "
    "Example: 'Debugging auth middleware after session tokens were stored incorrectly. "
    "Fixed token validation in auth.py, added integration tests, updated the migration. "
    "PR #42 is merged to main.'\n\n"
)


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


def generate_summary(cwd: str) -> str:
    """Generate a conversation summary using the Claude CLI.

    Returns the summary string, or empty string on failure.
    """
    claude_path = shutil.which("claude")
    if not claude_path:
        log.warning("summarize: claude CLI not found")
        return ""

    conversation = _extract_conversation_text(cwd)
    if not conversation:
        return ""

    try:
        result = subprocess.run(
            [claude_path, "-p", _PROMPT + conversation],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        log.warning("summarize: claude returned %d", result.returncode)
    except subprocess.TimeoutExpired:
        log.warning("summarize: claude timed out after %ds", _TIMEOUT_SECONDS)
    except OSError as e:
        log.warning("summarize: failed to run claude: %s", e)

    return ""


def quick_summary(cwd: str, max_len: int = 60) -> str:
    """Instant heuristic summary from JSONL — no API call.

    Returns the first user message (the intent) truncated to max_len.
    """
    path = find_most_recent_jsonl(cwd)
    if not path:
        return ""

    tail = read_jsonl_tail(path, tail_bytes=20000)
    if not tail:
        return ""

    first_user_msg = ""
    tool_count = 0
    for line in tail.strip().splitlines():
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        dtype = d.get("type", "")
        msg = d.get("message", {})
        if not isinstance(msg, dict):
            continue

        if dtype == "user" and not first_user_msg:
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                first_user_msg = content.strip().replace("\n", " ")

        elif dtype == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                tool_count += sum(1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use")

    if not first_user_msg:
        return ""

    summary = first_user_msg
    if len(summary) > max_len:
        summary = summary[: max_len - 1] + "…"
    if tool_count:
        summary += f" ({tool_count} tools)"
    return summary


def get_cached_summary(cwd: str) -> str | None:
    """Return cached summary if JSONL hasn't changed since it was generated."""
    entry = _summary_cache.get(cwd)
    if not entry:
        return None
    summary, cached_mtime = entry
    current_mtime = _get_jsonl_mtime(cwd)
    if current_mtime and current_mtime <= cached_mtime:
        return summary
    return None


def cache_summary(cwd: str, summary: str) -> None:
    """Store a summary keyed to the current JSONL mtime."""
    mtime = _get_jsonl_mtime(cwd) or time.time()
    _summary_cache[cwd] = (summary, mtime)


def _get_jsonl_mtime(cwd: str) -> float:
    """Get the modification time of the most recent JSONL for a CWD."""
    path = find_most_recent_jsonl(cwd)
    if path:
        try:
            return os.path.getmtime(path)
        except OSError:
            pass
    return 0.0


def generate_and_cache_summary(cwd: str) -> str:
    """Generate a rich summary via claude -p and cache it.

    Limits concurrency to _MAX_CONCURRENT and deduplicates in-flight requests.
    """
    cached = get_cached_summary(cwd)
    if cached is not None:
        return cached

    with _in_progress_lock:
        if cwd in _in_progress:
            return ""  # another thread is already generating for this CWD
        _in_progress.add(cwd)

    try:
        if not _semaphore.acquire(timeout=1):
            return ""  # too many concurrent summaries
        try:
            summary = generate_summary(cwd)
            if summary:
                cache_summary(cwd, summary)
            return summary
        finally:
            _semaphore.release()
    finally:
        with _in_progress_lock:
            _in_progress.discard(cwd)


def invalidate_cache(cwd: str) -> None:
    """Remove a CWD from the summary cache."""
    _summary_cache.pop(cwd, None)
