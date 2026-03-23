"""App configuration stored at ~/.claude/claudewatch.json."""

import json
import logging
import os

log = logging.getLogger("claudewatch")

_SETTINGS_PATH = os.path.expanduser("~/.claude/claudewatch.json")

_DEFAULTS: dict[str, object] = {
    "notifications_enabled": True,
    "poll_interval": 1,
    "notification_sound": "Glass",
    "pin_expiry_days": 30,
    "onboarding_tips_shown": [],
    "onboarding_session_count": 0,
}

_SOUNDS = ("Glass", "Blow", "Bottle", "Frog", "Funk", "Hero", "Morse", "Ping", "Pop", "Purr", "Submarine", "Tink")

_cache: dict[str, object] | None = None


def _load() -> dict[str, object]:
    global _cache  # noqa: PLW0603
    if _cache is not None:
        return _cache
    try:
        with open(_SETTINGS_PATH) as f:
            _cache = {**_DEFAULTS, **json.load(f)}
    except (OSError, json.JSONDecodeError):
        _cache = dict(_DEFAULTS)
    return _cache


def _save() -> None:
    if _cache is None:
        return
    try:
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(_cache, f, indent=2)
    except OSError:
        log.warning("Failed to save settings to %s", _SETTINGS_PATH)


def get_setting(key: str) -> object:
    return _load().get(key, _DEFAULTS.get(key))


def set_setting(key: str, value: object) -> None:
    _load()[key] = value
    _save()
    log.info("setting changed: %s=%s", key, value)


def get_available_sounds() -> tuple[str, ...]:
    return _SOUNDS
