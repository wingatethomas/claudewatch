"""Generate conversation summaries via the Claude CLI."""

import json
import logging
import shutil
import subprocess
import time

from claudewatch.backend.services.jsonl import find_most_recent_jsonl, read_jsonl_tail

log = logging.getLogger("claudewatch")

_MAX_CONTEXT_CHARS = 8000
_TIMEOUT_SECONDS = 15
_CACHE_TTL = 300  # 5 minutes

# CWD → (summary, timestamp)
_summary_cache: dict[str, tuple[str, float]] = {}
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
    """Return cached rich summary if available and fresh, else None."""
    entry = _summary_cache.get(cwd)
    if entry and time.time() - entry[1] < _CACHE_TTL:
        return entry[0]
    return None


def cache_summary(cwd: str, summary: str) -> None:
    """Store a rich summary in the cache."""
    _summary_cache[cwd] = (summary, time.time())


def generate_and_cache_summary(cwd: str) -> str:
    """Generate a rich summary via claude -p and cache it."""
    cached = get_cached_summary(cwd)
    if cached is not None:
        return cached

    summary = generate_summary(cwd)
    if summary:
        cache_summary(cwd, summary)
    return summary


def invalidate_cache(cwd: str) -> None:
    """Remove a CWD from the summary cache."""
    _summary_cache.pop(cwd, None)
