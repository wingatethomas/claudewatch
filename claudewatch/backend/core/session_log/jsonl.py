"""Shared JSONL file discovery and reading for Claude Code session logs."""

import json
import os

from claudewatch.backend.core.paths import CLAUDE_PROJECTS_DIR, cwd_to_proj_key
from claudewatch.backend.core.session_log.schema import FIELD_AI_TITLE, TYPE_AI_TITLE


def list_jsonls_in_cwd(cwd: str) -> list[str]:
    """List all JSONL paths in a CWD's project dir, sorted by mtime descending.

    Filters out symlink-traversal paths. Returns empty list on error.
    """
    proj_key = cwd_to_proj_key(cwd)
    proj_dir = os.path.join(CLAUDE_PROJECTS_DIR, proj_key)
    if not os.path.isdir(proj_dir):
        return []

    try:
        candidates = [os.path.join(proj_dir, f) for f in os.listdir(proj_dir) if f.endswith(".jsonl")]
        jsonls = sorted(
            (p for p in candidates if is_safe_jsonl_path(p)),
            key=os.path.getmtime,
            reverse=True,
        )
    except OSError:
        return []

    return jsonls


def find_most_recent_jsonl(cwd: str) -> str | None:
    """Find the most recently modified JSONL file for a CWD.

    Returns the full path, or None if not found or symlink traversal detected.
    """
    jsonls = list_jsonls_in_cwd(cwd)
    return jsonls[0] if jsonls else None


def is_safe_jsonl_path(path: str) -> bool:
    """Check that a JSONL path resolves to within CLAUDE_PROJECTS_DIR.

    Prevents symlink traversal attacks.
    """
    real_proj_dir = os.path.realpath(CLAUDE_PROJECTS_DIR)
    real_path = os.path.realpath(path)
    return real_path.startswith(real_proj_dir + os.sep)


def read_jsonl_tail(path: str, tail_bytes: int = 10240) -> str:
    """Read the last N bytes of a JSONL file as UTF-8 text.

    Returns empty string on error.
    """
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail_bytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def read_jsonl_full(path: str) -> list[str]:
    """Read all lines from a JSONL file.

    Returns empty list on error.
    """
    try:
        with open(path) as f:
            return f.readlines()
    except OSError:
        return []


def get_session_id_from_path(path: str) -> str:
    """Extract the session ID (UUID) from a JSONL filename."""
    return os.path.basename(path).removesuffix(".jsonl")


def read_ai_title(path: str, tail_bytes: int = 10240) -> str:
    """Return the latest aiTitle recorded in the JSONL, or "" if none.

    Claude Code writes `{"type":"ai-title","aiTitle":"..."}` periodically.
    We scan the tail in reverse so we pick up the most recent title.
    """
    tail = read_jsonl_tail(path, tail_bytes=tail_bytes)
    if not tail:
        return ""
    needle = f'"{TYPE_AI_TITLE}"'
    for line in reversed(tail.splitlines()):
        if needle not in line:
            continue
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if d.get("type") == TYPE_AI_TITLE:
            title = d.get(FIELD_AI_TITLE, "")
            if isinstance(title, str) and title:
                return title
    return ""
