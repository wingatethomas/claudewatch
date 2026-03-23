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


def get_session_tokens(cwd: str) -> dict[str, int]:
    """Get total token usage for the most recent session at a CWD.

    Returns {"input": N, "output": N} summed across all messages.
    Cached by JSONL mtime — only re-reads when the file changes.
    """
    path = find_most_recent_jsonl(cwd)
    if not path:
        return {"input": 0, "output": 0}

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {"input": 0, "output": 0}

    cached = _token_cache.get(cwd)
    if cached and cached[1] >= mtime:
        return cached[0]

    lines = read_jsonl_full(path)
    total_in = 0
    total_out = 0
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
        total_in += usage.get("cache_creation_input_tokens", 0)
        total_in += usage.get("cache_read_input_tokens", 0)
        total_out += usage.get("output_tokens", 0)

    result = {"input": total_in, "output": total_out}
    _token_cache[cwd] = (result, mtime)
    return result


def format_tokens(tokens: dict[str, int]) -> str:
    """Format token counts as a compact string like '12K in · 3K out'."""
    total = tokens["input"] + tokens["output"]
    if total == 0:
        return ""

    _m = 1_000_000
    _k = 1000

    def _fmt(n: int) -> str:
        if n >= _m:
            return f"{n / _m:.1f}M"
        if n >= _k:
            return f"{n / _k:.0f}K"
        return str(n)

    return f"{_fmt(tokens['input'])} in · {_fmt(tokens['output'])} out"
