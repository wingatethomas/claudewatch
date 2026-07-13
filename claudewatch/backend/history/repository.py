"""Session history — auto-recorded when sessions end."""

import json
import logging
import os
import threading
from datetime import UTC, datetime
from typing import TypedDict

from claudewatch.backend.core.dto import HistoryEntryDTO
from claudewatch.backend.core.helpers import atomic_json_write
from claudewatch.backend.core.paths import CLAUDE_PROJECTS_DIR, HISTORY_PATH, proj_key_to_cwd
from claudewatch.backend.core.session_log.jsonl import is_safe_jsonl_path, read_jsonl_tail

log = logging.getLogger("claudewatch")

_PATH = HISTORY_PATH
_MAX_ENTRIES = 50

# Serializes read-modify-write of the history JSON file across threads.
_LOCK = threading.Lock()

# Stale model values from earlier versions that stored display names directly,
# or from JSONL placeholders. Mapped back to a raw model id (or "" when no
# canonical id exists) so the display layer renders one consistent format.
_STALE_MODEL_MAP: dict[str, str] = {
    "o4.6": "claude-opus-4-6",
    "opus 4.6": "claude-opus-4-6",
    "s4.6": "claude-sonnet-4-6",
    "sonnet 4.6": "claude-sonnet-4-6",
    "h4.5": "claude-haiku-4-5",
    "haiku 4.5": "claude-haiku-4-5",
    "s4.5": "claude-sonnet-4-5-20250514",
    "sonnet 4.5": "claude-sonnet-4-5-20250514",
    "o4": "claude-opus-4-20250512",
    "opus 4": "claude-opus-4-20250512",
    "<synthetic>": "",
}


class _HistoryRecord(TypedDict):
    session_id: str
    project: str
    cwd: str
    model: str
    host_app: str
    ended_at: str


def _normalize_model(value: str) -> str:
    """Translate stale display-name or placeholder values back to raw ids."""
    return _STALE_MODEL_MAP.get(value, value)


def _load() -> list[_HistoryRecord]:
    try:
        with open(_PATH) as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
    except (OSError, json.JSONDecodeError):
        return []
    mutated = False
    if len(data) > _MAX_ENTRIES:
        data = data[-_MAX_ENTRIES:]
        mutated = True
    for entry in data:
        original = entry.get("model", "")
        normalized = _normalize_model(original)
        if normalized != original:
            entry["model"] = normalized
            mutated = True
    if mutated:
        _save(data)
    return data


def _save(entries: list[_HistoryRecord]) -> None:
    try:
        atomic_json_write(_PATH, entries)
    except OSError:
        log.warning("Failed to save history to %s", _PATH)


def record_session(session_id: str, project: str, cwd: str, model: str, host_app: str) -> None:
    """Record a session when it ends. Deduplicates by session id (CWD for legacy entries without one)."""
    with _LOCK:
        entries = _load()
        ts = datetime.now(tz=UTC).isoformat()
        if session_id:
            entries = [e for e in entries if e.get("session_id") != session_id]
        else:
            entries = [e for e in entries if e.get("session_id") or e["cwd"] != cwd]
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
    """Return session history, newest first. Seeds from JSONL on first call.

    Only seeds when the history file does not yet exist on disk. Once the file
    exists, an empty list is treated as "user cleared their history" and is
    left empty — otherwise deleted entries would reappear from ~/.claude/.
    """
    with _LOCK:
        entries = _load()
        if not entries and not os.path.exists(_PATH):
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
                    if m and m != "<synthetic>":
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


def remove_history_entry(session_id: str, cwd: str = "") -> None:
    """Remove a history entry by session id (CWD match for legacy entries without one)."""
    with _LOCK:
        entries = _load()
        if session_id:
            entries = [e for e in entries if e.get("session_id") != session_id]
        else:
            entries = [e for e in entries if e.get("session_id") or e["cwd"] != cwd]
        _save(entries)
