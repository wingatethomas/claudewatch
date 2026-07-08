"""Pinned session bookmarks."""

import json
import logging
import threading
from datetime import UTC, datetime
from typing import TypedDict

from claudewatch.backend.core import features
from claudewatch.backend.core.dto import BookmarkDTO
from claudewatch.backend.core.features import FeatureKey
from claudewatch.backend.core.helpers import atomic_json_write
from claudewatch.backend.core.paths import PINS_PATH

log = logging.getLogger("claudewatch")

_PATH = PINS_PATH

# Serializes read-modify-write of the bookmarks JSON file across threads.
_LOCK = threading.Lock()


class _BookmarkRecord(TypedDict):
    session_id: str
    project: str
    cwd: str
    note: str
    timestamp: str


def _load() -> list[_BookmarkRecord]:
    try:
        with open(_PATH) as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
    except (OSError, json.JSONDecodeError):
        return []
    raw = features.get_facet(FeatureKey.BOOKMARKS, "expiry_days") or "30 days"
    try:
        ttl_days = 0 if raw == "Never" else int(str(raw).rstrip(" days"))
    except (ValueError, TypeError):
        ttl_days = 30
    if ttl_days <= 0:  # "Never" = no expiry
        return data
    cutoff = datetime.now(tz=UTC).timestamp() - ttl_days * 86400
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


def _save(pins: list[_BookmarkRecord]) -> None:
    try:
        atomic_json_write(_PATH, pins)
    except OSError:
        log.warning("Failed to save pins to %s", _PATH)


def add_bookmark(session_id: str, project: str, cwd: str, note: str) -> None:
    """Bookmark a session with a note. Updates if already bookmarked.

    Keyed by session_id: multiple sessions sharing a CWD each get their own
    bookmark. Entries without a session_id (legacy) match by CWD.
    """
    with _LOCK:
        bookmarks = _load()
        ts = datetime.now(tz=UTC).isoformat()
        for entry in bookmarks:
            same_session = bool(session_id) and entry.get("session_id") == session_id
            legacy_same_cwd = not session_id and not entry.get("session_id") and entry["cwd"] == cwd
            if same_session or legacy_same_cwd:
                entry["session_id"] = session_id
                entry["note"] = note
                entry["timestamp"] = ts
                _save(bookmarks)
                log.info("bookmark.updated project=%s", project)
                return
        bookmarks.append(
            _BookmarkRecord(
                session_id=session_id,
                project=project,
                cwd=cwd,
                note=note,
                timestamp=ts,
            )
        )
        _save(bookmarks)
    log.info("bookmark.created project=%s", project)


def get_bookmarks() -> list[BookmarkDTO]:
    """Return all bookmarked sessions as DTOs."""
    with _LOCK:
        pins = _load()
    return [
        BookmarkDTO(
            session_id=p.get("session_id", ""),
            project=p.get("project", ""),
            cwd=p.get("cwd", ""),
            note=p.get("note", ""),
            timestamp=p.get("timestamp", ""),
        )
        for p in pins
    ]


def get_bookmarked_cwds() -> set[str]:
    """Return the set of CWDs that are bookmarked."""
    with _LOCK:
        return {p["cwd"] for p in _load()}


def clear_all_bookmarks() -> None:
    """Delete all bookmarks."""
    with _LOCK:
        _save([])
    log.info("bookmark.cleared_all")


def remove_bookmark(session_id: str, cwd: str = "") -> None:
    """Remove a bookmark by session id (CWD match for legacy entries without one)."""
    with _LOCK:
        bookmarks = _load()
        before = len(bookmarks)
        if session_id:
            bookmarks = [p for p in bookmarks if p.get("session_id") != session_id]
        else:
            bookmarks = [p for p in bookmarks if p.get("session_id") or p["cwd"] != cwd]
        if len(bookmarks) < before:
            log.info("bookmark.removed session=%s cwd=%s", session_id, cwd)
        _save(bookmarks)
