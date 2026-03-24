"""Session history — auto-recorded when sessions end."""

import json
import logging
import os
from datetime import UTC, datetime

from claudewatch.backend.core.models import CLAUDE_PROJECTS_DIR, proj_key_to_cwd
from claudewatch.backend.core.paths import HISTORY_PATH
from claudewatch.backend.core.session_log.jsonl import is_safe_jsonl_path, read_jsonl_tail

log = logging.getLogger("claudewatch")

_PATH = HISTORY_PATH
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
    entries.append(
        {
            "session_id": session_id,
            "project": project,
            "cwd": cwd,
            "model": model,
            "host_app": host_app,
            "ended_at": ts,
        }
    )
    # Cap at max
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    _save(entries)
    log.info("history.recorded project=%s", project)


def get_history() -> list[dict]:
    """Return session history, newest first. Seeds from JSONL on first call."""
    entries = _load()
    if not entries:
        entries = _seed_from_jsonl()
    return list(reversed(entries))


def _seed_from_jsonl() -> list[dict]:
    """Scan ~/.claude/projects/ for existing sessions and populate history."""
    if not os.path.isdir(CLAUDE_PROJECTS_DIR):
        return []

    entries: list[dict] = []
    try:
        for proj_key in os.listdir(CLAUDE_PROJECTS_DIR):
            proj_dir = os.path.join(CLAUDE_PROJECTS_DIR, proj_key)
            if not os.path.isdir(proj_dir):
                continue
            jsonls = [f for f in os.listdir(proj_dir) if f.endswith(".jsonl")]
            if not jsonls:
                continue
            # Most recent JSONL
            jsonls.sort(key=lambda f: os.path.getmtime(os.path.join(proj_dir, f)), reverse=True)
            session_id = jsonls[0].removesuffix(".jsonl")
            cwd = proj_key_to_cwd(proj_key)
            project = os.path.basename(cwd)
            # Get model from last few lines
            model = ""
            jsonl_path = os.path.join(proj_dir, jsonls[0])
            if not is_safe_jsonl_path(jsonl_path):
                continue
            tail = read_jsonl_tail(jsonl_path, tail_bytes=5120)
            for line in tail.strip().splitlines():
                try:
                    d = json.loads(line)
                    m = d.get("message", {}).get("model", "")
                    if m:
                        model = m
                except (json.JSONDecodeError, AttributeError):
                    pass

            mtime = os.path.getmtime(jsonl_path)
            entries.append(
                {
                    "session_id": session_id,
                    "project": project,
                    "cwd": cwd,
                    "model": model,
                    "host_app": "Terminal",
                    "ended_at": datetime.fromtimestamp(mtime, tz=UTC).isoformat(),
                }
            )
    except OSError:
        return []

    entries.sort(key=lambda e: e.get("ended_at", ""))
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    _save(entries)
    log.info("history.seeded count=%d", len(entries))
    return entries


def remove_history_entry(cwd: str) -> None:
    """Remove a history entry by CWD."""
    entries = _load()
    entries = [e for e in entries if not (isinstance(e, dict) and e.get("cwd") == cwd)]
    _save(entries)
