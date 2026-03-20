"""Parse session metadata from Claude Code JSONL session logs."""

import json
import os

CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

# Model display names — keep factual
_MODEL_NAMES: dict[str, str] = {
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
    proj_key = cwd.replace("/", "-")
    proj_dir = os.path.join(CLAUDE_PROJECTS_DIR, proj_key)
    if not os.path.isdir(proj_dir):
        return ""

    try:
        jsonls = sorted(
            [os.path.join(proj_dir, f) for f in os.listdir(proj_dir) if f.endswith(".jsonl")],
            key=os.path.getmtime,
            reverse=True,
        )
    except OSError:
        return ""

    if not jsonls:
        return ""

    # Validate symlink traversal
    real_proj_dir = os.path.realpath(CLAUDE_PROJECTS_DIR)
    real_jsonl = os.path.realpath(jsonls[0])
    if not real_jsonl.startswith(real_proj_dir + os.sep):
        return ""

    # Read last ~10KB — model is in every assistant message
    try:
        with open(jsonls[0], "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 10240))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
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

    return _MODEL_NAMES.get(last_model, last_model)
