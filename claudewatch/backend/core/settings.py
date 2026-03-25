"""App settings backed by NSUserDefaults.

Reads/writes to keys prefixed with 'com.claudewatch.' in the standard
user defaults domain. On first run, migrates any existing settings.json.
"""

import json
import logging
import os

from Foundation import NSUserDefaults

log = logging.getLogger("claudewatch")

_SUITE = "com.claudewatch"
_defaults = NSUserDefaults.standardUserDefaults()

_DEFAULTS: dict[str, object] = {
    "notifications_enabled": True,
    "poll_interval": 1,
    "notification_sound": "Glass",
    "pin_expiry_days": 30,
    "onboarding_tips_shown": [],
    "onboarding_session_count": 0,
}

_SOUNDS = ("Glass", "Blow", "Bottle", "Frog", "Funk", "Hero", "Morse", "Ping", "Pop", "Purr", "Submarine", "Tink")

# Legacy path for JSON migration
_LEGACY_SETTINGS_PATH = os.path.expanduser("~/Library/Application Support/ClaudeWatch/settings.json")


def get_setting(key: str) -> object:
    """Read a setting. Returns the stored value, or the default, or None."""
    val = _defaults.objectForKey_(f"{_SUITE}.{key}")
    if val is not None:
        return val
    return _DEFAULTS.get(key)


def set_setting(key: str, value: object) -> None:
    """Write a setting to NSUserDefaults."""
    _defaults.setObject_forKey_(value, f"{_SUITE}.{key}")
    log.info("setting changed: %s=%s", key, value)


def get_available_sounds() -> tuple[str, ...]:
    return _SOUNDS


def _migrate_from_json() -> None:
    """One-time migration: read settings.json into NSUserDefaults."""
    if _defaults.objectForKey_(f"{_SUITE}._migrated"):
        return

    if not os.path.exists(_LEGACY_SETTINGS_PATH):
        return

    try:
        with open(_LEGACY_SETTINGS_PATH) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        log.warning("Failed to read legacy settings from %s", _LEGACY_SETTINGS_PATH)
        return

    if not isinstance(data, dict):
        return

    for key, value in data.items():
        _defaults.setObject_forKey_(value, f"{_SUITE}.{key}")

    _defaults.setObject_forKey_(True, f"{_SUITE}._migrated")

    try:
        os.rename(_LEGACY_SETTINGS_PATH, _LEGACY_SETTINGS_PATH + ".migrated")
        log.info("Migrated settings.json to NSUserDefaults")
    except OSError:
        log.warning("Could not rename legacy settings file")


def ensure_defaults_migrated() -> None:
    """Call at app startup to trigger migration if needed."""
    _migrate_from_json()
