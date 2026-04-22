"""Session history — auto-recorded when sessions end."""

import json
import logging
import os
from datetime import UTC, datetime
from typing import TypedDict

from claudewatch.backend.core.dto import HistoryEntryDTO
from claudewatch.backend.core.paths import CLAUDE_PROJECTS_DIR, HISTORY_PATH, proj_key_to_cwd
from claudewatch.backend.core.session_log.jsonl import is_safe_jsonl_path, read_jsonl_tail

log = logging.getLogger("claudewatch")

_PATH = HISTORY_PATH
_MAX_ENTRIES = 50


class _HistoryRecord(TypedDict):
    session_id: str
    project: str
    cwd: str
    model: str
    host_app: str
    ended_at: str


def _load() -> list[_HistoryRecord]:
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


def _save(entries: list[_HistoryRecord]) -> None:
    tmp = _PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp, _PATH)
    except OSError:
        log.warning("Failed to save history to %s", _PATH)


def record_session(session_id: str, project: str, cwd: str, model: str, host_app: str) -> None:
    """Record a session when it ends. Deduplicates by CWD (keeps latest)."""
    entries = _load()
    ts = datetime.now(tz=UTC).isoformat()
    entries = [e for e in entries if e["cwd"] != cwd]
    entries.append(
        _HistoryRecord(
            session_id=session_id,
            project=project,
            cwd=cwd,
            model=model,
            host_app=host_app,
            ended_at=ts,
        )
    )
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    _save(entries)
    log.info("history.recorded project=%s", project)


def get_history() -> list[HistoryEntryDTO]:
    """Return session history, newest first. Seeds from JSONL on first call."""
    entries = _load()
    if not entries:
        entries = _seed_from_jsonl()
    return [
        HistoryEntryDTO(
            session_id=e.get("session_id", ""),
            project=e.get("project", ""),
            cwd=e.get("cwd", ""),
            model=e.get("model", ""),
            host_app=e.get("host_app", ""),
            ended_at=e.get("ended_at", ""),
        )
        for e in reversed(entries)
    ]


def _seed_from_jsonl() -> list[_HistoryRecord]:
    """Scan ~/.claude/projects/ for existing sessions and populate history."""
    if not os.path.isdir(CLAUDE_PROJECTS_DIR):
        return []

    entries: list[_HistoryRecord] = []
    try:
        for proj_key in os.listdir(CLAUDE_PROJECTS_DIR):
            proj_dir = os.path.join(CLAUDE_PROJECTS_DIR, proj_key)
            if not os.path.isdir(proj_dir):
                continue
            jsonls = [f for f in os.listdir(proj_dir) if f.endswith(".jsonl")]
            if not jsonls:
                continue
            jsonls.sort(key=lambda f: os.path.getmtime(os.path.join(proj_dir, f)), reverse=True)
            session_id = jsonls[0].removesuffix(".jsonl")
            cwd = proj_key_to_cwd(proj_key)
            project = os.path.basename(cwd)
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
                _HistoryRecord(
                    session_id=session_id,
                    project=project,
                    cwd=cwd,
                    model=model,
                    host_app="Terminal",
                    ended_at=datetime.fromtimestamp(mtime, tz=UTC).isoformat(),
                )
            )
    except OSError:
        return []

    entries.sort(key=lambda e: e["ended_at"])
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    _save(entries)
    log.info("history.seeded count=%d", len(entries))
    return entries


def remove_history_entry(cwd: str) -> None:
    """Remove a history entry by CWD."""
    entries = _load()
    entries = [e for e in entries if e["cwd"] != cwd]
    _save(entries)
