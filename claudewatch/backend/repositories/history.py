"""Session history — auto-recorded when sessions end."""

import json
import logging
import os
from datetime import UTC, datetime

log = logging.getLogger("claudewatch")

_PATH = os.path.expanduser("~/.claude/claudewatch-history.json")
_MAX_ENTRIES = 50


def _load() -> list[dict]:
    try:
        with open(_PATH) as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
    except (OSError, json.JSONDecodeError):
        return []
    # Prune to max size
    if len(data) > _MAX_ENTRIES:
        data = data[-_MAX_ENTRIES:]
        _save(data)
    return data


def _save(entries: list[dict]) -> None:
    try:
        with open(_PATH, "w") as f:
            json.dump(entries, f, indent=2)
    except OSError:
        log.warning("Failed to save history to %s", _PATH)


def record_session(session_id: str, project: str, cwd: str, model: str, host_app: str) -> None:
    """Record a session when it ends. Deduplicates by CWD (keeps latest)."""
    entries = _load()
    ts = datetime.now(tz=UTC).isoformat()
    # Remove existing entry for same CWD (keep only latest)
    entries = [e for e in entries if not (isinstance(e, dict) and e.get("cwd") == cwd)]
    entries.append({
        "session_id": session_id,
        "project": project,
        "cwd": cwd,
        "model": model,
        "host_app": host_app,
        "ended_at": ts,
    })
    # Cap at max
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    _save(entries)
    log.info("history.recorded project=%s", project)


def get_history() -> list[dict]:
    """Return session history, newest first."""
    return list(reversed(_load()))


def remove_history_entry(cwd: str) -> None:
    """Remove a history entry by CWD."""
    entries = _load()
    entries = [e for e in entries if not (isinstance(e, dict) and e.get("cwd") == cwd)]
    _save(entries)
