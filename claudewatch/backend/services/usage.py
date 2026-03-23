"""Parse session metadata from Claude Code JSONL session logs."""

import json

from claudewatch.backend.services.jsonl import find_most_recent_jsonl, read_jsonl_tail

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
