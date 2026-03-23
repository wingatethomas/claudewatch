"""Parse session metadata from Claude Code JSONL session logs."""

import json
import os

from claudewatch.backend.services.jsonl import find_most_recent_jsonl, read_jsonl_full, read_jsonl_tail

# CWD → (tokens_dict, jsonl_mtime)
_token_cache: dict[str, tuple[dict[str, int], float]] = {}

# Model display names — keep factual
MODEL_DISPLAY_NAMES: dict[str, str] = {
    "claude-opus-4-6": "opus 4.6",
    "claude-sonnet-4-6": "sonnet 4.6",
    "claude-haiku-4-5": "haiku 4.5",
    "claude-sonnet-4-5-20250514": "sonnet 4.5",
    "claude-opus-4-20250512": "opus 4",
}


def get_session_model(cwd: str) -> str:
    """Get the model name for the most recent session at a CWD.

    Reads the last assistant message from the JSONL to find the model.
    Returns a display name like 'opus 4.6' or empty string if unavailable.
    """
    path = find_most_recent_jsonl(cwd)
    if not path:
        return ""

    tail = read_jsonl_tail(path)
    if not tail:
        return ""

    last_model = ""
    for line in tail.strip().splitlines():
        try:
            d = json.loads(line)
            msg = d.get("message", {})
            if isinstance(msg, dict):
                model = msg.get("model", "")
                if model:
                    last_model = model
        except (json.JSONDecodeError, AttributeError):
            continue

    return MODEL_DISPLAY_NAMES.get(last_model, last_model)


_EMPTY_TOKENS: dict[str, int] = {
    "input": 0,
    "output": 0,
    "cache_create": 0,
    "cache_read": 0,
}


def get_session_tokens(cwd: str) -> dict[str, int]:
    """Get token usage breakdown for the most recent session at a CWD.

    Returns {input, output, cache_create, cache_read} summed across all messages.
    Cached by JSONL mtime — only re-reads when the file changes.
    """
    path = find_most_recent_jsonl(cwd)
    if not path:
        return dict(_EMPTY_TOKENS)

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return dict(_EMPTY_TOKENS)

    cached = _token_cache.get(cwd)
    if cached and cached[1] >= mtime:
        return cached[0]

    lines = read_jsonl_full(path)
    total_in = 0
    total_out = 0
    total_cache_create = 0
    total_cache_read = 0
    for line in lines:
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        msg = d.get("message", {})
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage", {})
        if not isinstance(usage, dict):
            continue
        total_in += usage.get("input_tokens", 0)
        total_cache_create += usage.get("cache_creation_input_tokens", 0)
        total_cache_read += usage.get("cache_read_input_tokens", 0)
        total_out += usage.get("output_tokens", 0)

    result = {
        "input": total_in,
        "output": total_out,
        "cache_create": total_cache_create,
        "cache_read": total_cache_read,
    }
    _token_cache[cwd] = (result, mtime)
    return result


_M = 1_000_000
_K = 1000


def _fmt_tokens(n: int) -> str:
    """Format a token count as compact string (e.g. 42K, 1.2M)."""
    if n >= _M:
        return f"{n / _M:.1f}M"
    if n >= _K:
        return f"{n / _K:.0f}K"
    return str(n)


def format_tokens(tokens: dict[str, int]) -> str:
    """Compact one-line format for detail line: '42K in · 3K out'."""
    total_in = tokens["input"] + tokens["cache_create"] + tokens["cache_read"]
    total_out = tokens["output"]
    if total_in + total_out == 0:
        return ""
    return f"{_fmt_tokens(total_in)} in · {_fmt_tokens(total_out)} out"


def format_tokens_breakdown(tokens: dict[str, int]) -> list[str]:
    """Detailed breakdown lines for a submenu."""
    total_in = tokens["input"] + tokens["cache_create"] + tokens["cache_read"]
    total_out = tokens["output"]
    if total_in + total_out == 0:
        return []
    lines = [
        f"Input: {_fmt_tokens(tokens['input'])} tokens",
        f"Output: {_fmt_tokens(total_out)} tokens",
    ]
    if tokens["cache_create"]:
        lines.append(f"Cache write: {_fmt_tokens(tokens['cache_create'])} tokens")
    if tokens["cache_read"]:
        lines.append(f"Cache read: {_fmt_tokens(tokens['cache_read'])} tokens")
    lines.append(f"Total: {_fmt_tokens(total_in + total_out)} tokens")
    return lines
