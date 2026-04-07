"""App settings backed by NSUserDefaults.

Uses an explicit suite domain ('com.claudewatch') so settings persist
regardless of how the app is launched — dev (uv run), Homebrew (.app),
or Briefcase bundle. Keys are prefixed with 'com.claudewatch.' within
the suite for namespacing.

On first run, migrates settings from legacy JSON and from the old
standardUserDefaults domain (which varied by bundle ID).
"""

import json
import logging
import os

from Foundation import NSUserDefaults

log = logging.getLogger("claudewatch")

_SUITE = "com.claudewatch"
_defaults = NSUserDefaults.alloc().initWithSuiteName_(_SUITE)

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
    """Write a setting to NSUserDefaults suite domain.

    Also removes the key from standardUserDefaults to prevent stale values
    from the old bundle-ID-scoped domain from shadowing the suite write.
    """
    full_key = f"{_SUITE}.{key}"
    _defaults.setObject_forKey_(value, full_key)
    # Clear stale value from standard domain so it doesn't shadow the suite
    std = NSUserDefaults.standardUserDefaults()
    if std.objectForKey_(full_key) is not None:
        std.removeObjectForKey_(full_key)
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


def _migrate_from_standard_defaults() -> None:
    """One-time migration: copy settings from standardUserDefaults to the suite domain.

    Before this fix, settings were written to standardUserDefaults() which uses
    the app's bundle identifier as the domain. Homebrew .app and dev (uv run)
    had different bundle IDs, so settings didn't carry over between them.
    """
    if _defaults.objectForKey_(f"{_SUITE}._suite_migrated"):
        return

    std = NSUserDefaults.standardUserDefaults()
    migrated_count = 0
    for key in std.dictionaryRepresentation():
        if not isinstance(key, str) or not key.startswith(f"{_SUITE}."):
            continue
        # Only copy if not already in suite domain
        if _defaults.objectForKey_(key) is None:
            val = std.objectForKey_(key)
            if val is not None:
                _defaults.setObject_forKey_(val, key)
                migrated_count += 1

    _defaults.setObject_forKey_(True, f"{_SUITE}._suite_migrated")
    if migrated_count > 0:
        log.info("Migrated %d settings from standardUserDefaults to suite domain", migrated_count)


def ensure_defaults_migrated() -> None:
    """Call at app startup to trigger migration if needed."""
    _migrate_from_json()
    _migrate_from_standard_defaults()
