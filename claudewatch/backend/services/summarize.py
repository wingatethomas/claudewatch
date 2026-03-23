"""Generate conversation summaries via the Claude CLI."""

import json
import logging
import shutil
import subprocess

from claudewatch.backend.services.jsonl import find_most_recent_jsonl, read_jsonl_tail

log = logging.getLogger("claudewatch")

_MAX_CONTEXT_CHARS = 8000
_TIMEOUT_SECONDS = 15
_PROMPT = (
    "Summarize this Claude Code conversation in 1-2 concise sentences. "
    "Focus on what the user was trying to accomplish and the current state. "
    "Do not use markdown. Do not start with 'The user' or 'This conversation'. "
    "Example: 'Debugging auth middleware — fixed session token storage, added tests, PR ready for review.'\n\n"
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
