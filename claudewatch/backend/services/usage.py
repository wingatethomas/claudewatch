"""Parse token usage from Claude Code JSONL session logs."""

import json
import os

CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

# Model context windows — verified from Anthropic docs
_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-sonnet-4-5-20250514": 200_000,
    "claude-opus-4-20250512": 200_000,
}
_DEFAULT_CONTEXT = 200_000


def get_session_usage(cwd: str) -> dict:  # noqa: PLR0911
    """Get token usage for the most recent session at a CWD.

    Reads the last usage entry from the JSONL — this contains the actual
    current context size for the conversation. Returns:
    {"context_tokens": int, "context_pct": int, "model": str}
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

    # Read last ~20KB — we only need the most recent usage entry
    try:
        with open(jsonls[0], "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 20480))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {}

    last_model = ""
    last_context = 0

    for line in tail.strip().splitlines():
        try:
            d = json.loads(line)
            msg = d.get("message", {})
            if not isinstance(msg, dict):
                continue
            model = msg.get("model")
            if model:
                last_model = model
            usage = msg.get("usage")
            if usage and isinstance(usage, dict):
                # Total context = all input tokens (fresh + cached)
                context = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                )
                if context > 0:
                    last_context = context
        except (json.JSONDecodeError, AttributeError):
            continue

    if not last_context:
        return {}

    window = _CONTEXT_WINDOWS.get(last_model, _DEFAULT_CONTEXT)
    pct = min(round(last_context / window * 100), 100)

    return {
        "context_tokens": last_context,
        "context_pct": pct,
        "model": last_model,
    }
