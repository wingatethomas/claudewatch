"""Saved session bookmarks stored at ~/.claude/claudewatch-sessions.json."""

import json
import logging
import os
from datetime import UTC, datetime

log = logging.getLogger("claudewatch")

_PATH = os.path.expanduser("~/.claude/claudewatch-sessions.json")
_TTL_DAYS = 30


def _load() -> list[dict]:
    try:
        with open(_PATH) as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
    except (OSError, json.JSONDecodeError):
        return []
    # Prune expired entries
    cutoff = datetime.now(tz=UTC).timestamp() - _TTL_DAYS * 86400
    alive = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            ts = datetime.fromisoformat(entry.get("timestamp", "")).timestamp()
            if ts > cutoff:
                alive.append(entry)
        except (ValueError, TypeError):
            alive.append(entry)
    if len(alive) != len(data):
        _save(alive)
    return alive


def _save(sessions: list[dict]) -> None:
    try:
        with open(_PATH, "w") as f:
            json.dump(sessions, f, indent=2)
    except OSError:
        log.warning("Failed to save bookmarks to %s", _PATH)


def save_bookmark(session_id: str, project: str, cwd: str, note: str) -> None:
    """Save or update a session bookmark."""
    saved = _load()
    ts = datetime.now(tz=UTC).isoformat()
    for entry in saved:
        if isinstance(entry, dict) and entry.get("session_id") == session_id:
            entry["note"] = note
            entry["timestamp"] = ts
            _save(saved)
            log.info("bookmark updated: %s project=%s", session_id[:8], project)
            return
    saved.append({
        "session_id": session_id,
        "project": project,
        "cwd": cwd,
        "note": note,
        "timestamp": ts,
    })
    _save(saved)
    log.info("bookmark saved: %s project=%s", session_id[:8], project)


def get_bookmarks() -> list[dict]:
    """Return all saved bookmarks."""
    return _load()


def remove_bookmark(session_id: str) -> None:
    """Remove a bookmark by session ID."""
    saved = _load()
    saved = [s for s in saved if not (isinstance(s, dict) and s.get("session_id") == session_id)]
    _save(saved)
