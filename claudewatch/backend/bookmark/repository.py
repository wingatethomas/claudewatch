"""Pinned session bookmarks."""

import json
import logging
from datetime import UTC, datetime

from claudewatch.backend.core import features
from claudewatch.backend.core.paths import PINS_PATH

log = logging.getLogger("claudewatch")

_PATH = PINS_PATH


def _load() -> list[dict]:
    try:
        with open(_PATH) as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
    except (OSError, json.JSONDecodeError):
        return []
    raw = features.get_facet("bookmarks", "expiry_days") or "30 days"
    ttl_days = 0 if raw == "Never" else int(str(raw).rstrip(" days"))
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


def _save(pins: list[dict]) -> None:
    try:
        with open(_PATH, "w") as f:
            json.dump(pins, f, indent=2)
    except OSError:
        log.warning("Failed to save pins to %s", _PATH)


def pin_session(session_id: str, project: str, cwd: str, note: str) -> None:
    """Pin a session with a note. Updates if already pinned."""
    pins = _load()
    ts = datetime.now(tz=UTC).isoformat()
    # Match by CWD (session IDs change between runs)
    for entry in pins:
        if isinstance(entry, dict) and entry.get("cwd") == cwd:
            entry["session_id"] = session_id
            entry["note"] = note
            entry["timestamp"] = ts
            _save(pins)
            log.info("pin.updated project=%s", project)
            return
    pins.append(
        {
            "session_id": session_id,
            "project": project,
            "cwd": cwd,
            "note": note,
            "timestamp": ts,
        }
    )
    _save(pins)
    log.info("pin.created project=%s", project)


def get_pins() -> list[dict]:
    """Return all pinned sessions."""
    return _load()


def get_pinned_cwds() -> set[str]:
    """Return the set of CWDs that are pinned — for quick lookup."""
    return {p.get("cwd", "") for p in _load() if isinstance(p, dict)}


def unpin_session(cwd: str) -> None:
    """Unpin a session by CWD."""
    pins = _load()
    before = len(pins)
    pins = [p for p in pins if not (isinstance(p, dict) and p.get("cwd") == cwd)]
    if len(pins) < before:
        log.info("pin.removed cwd=%s", cwd)
    _save(pins)
