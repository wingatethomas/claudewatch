"""Parse token usage from Claude Code JSONL session logs."""

import json
import os

CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
_CONTEXT_WINDOW = 200_000  # Opus/Sonnet context window


def get_session_usage(cwd: str) -> dict:  # noqa: PLR0911
    """Get token usage for the most recent session at a CWD.

    Returns {"input_tokens": int, "output_tokens": int, "context_pct": int}
    or empty dict if unavailable.
    """
    proj_key = cwd.replace("/", "-")
    proj_dir = os.path.join(CLAUDE_PROJECTS_DIR, proj_key)
    if not os.path.isdir(proj_dir):
        return {}

    try:
        jsonls = sorted(
            [os.path.join(proj_dir, f) for f in os.listdir(proj_dir) if f.endswith(".jsonl")],
            key=os.path.getmtime,
            reverse=True,
        )
    except OSError:
        return {}

    if not jsonls:
        return {}

    # Validate symlink traversal
    real_proj_dir = os.path.realpath(CLAUDE_PROJECTS_DIR)
    real_jsonl = os.path.realpath(jsonls[0])
    if not real_jsonl.startswith(real_proj_dir + os.sep):
        return {}

    # Read last ~50KB to find recent usage entries
    try:
        with open(jsonls[0], "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 51200))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {}

    max_input = 0
    total_output = 0

    for line in tail.strip().splitlines():
        try:
            d = json.loads(line)
            usage = d.get("message", {}).get("usage")
            if not usage:
                continue
            inp = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
            out = usage.get("output_tokens", 0)
            max_input = max(max_input, inp)
            total_output += out
        except (json.JSONDecodeError, AttributeError):
            continue

    if not max_input and not total_output:
        return {}

    return {
        "input_tokens": max_input,
        "output_tokens": total_output,
        "context_pct": min(round(max_input / _CONTEXT_WINDOW * 100), 100),
    }
