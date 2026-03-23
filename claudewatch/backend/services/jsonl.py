"""Shared JSONL file discovery and reading for Claude Code session logs."""

import os

from claudewatch.backend.models import CLAUDE_PROJECTS_DIR, cwd_to_proj_key


def find_most_recent_jsonl(cwd: str) -> str | None:
    """Find the most recently modified JSONL file for a CWD.

    Returns the full path, or None if not found or symlink traversal detected.
    """
    proj_key = cwd_to_proj_key(cwd)
    proj_dir = os.path.join(CLAUDE_PROJECTS_DIR, proj_key)
    if not os.path.isdir(proj_dir):
        return None

    try:
        jsonls = sorted(
            [os.path.join(proj_dir, f) for f in os.listdir(proj_dir) if f.endswith(".jsonl")],
            key=os.path.getmtime,
            reverse=True,
        )
    except OSError:
        return None

    if not jsonls:
        return None

    # Validate resolved path stays within projects dir (prevent symlink traversal)
    real_proj_dir = os.path.realpath(CLAUDE_PROJECTS_DIR)
    real_jsonl = os.path.realpath(jsonls[0])
    if not real_jsonl.startswith(real_proj_dir + os.sep):
        return None

    return jsonls[0]


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
