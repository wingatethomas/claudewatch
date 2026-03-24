"""Centralized app data paths.

All ClaudeWatch data lives in ~/Library/Application Support/ClaudeWatch/.
On first run, existing files are migrated from ~/.claude/claudewatch-*.
"""

import logging
import os
import shutil

log = logging.getLogger("claudewatch")

DATA_DIR = os.path.expanduser("~/Library/Application Support/ClaudeWatch")
LOG_DIR = DATA_DIR

# Individual file paths
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
PINS_PATH = os.path.join(DATA_DIR, "pins.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
SUMMARIES_PATH = os.path.join(DATA_DIR, "summaries.json")
LOG_PATH = os.path.join(LOG_DIR, "claudewatch.log")

# Legacy paths (for migration)
_LEGACY_DIR = os.path.expanduser("~/.claude")
_MIGRATIONS = {
    os.path.join(_LEGACY_DIR, "claudewatch.json"): SETTINGS_PATH,
    os.path.join(_LEGACY_DIR, "claudewatch-pins.json"): PINS_PATH,
    os.path.join(_LEGACY_DIR, "claudewatch-history.json"): HISTORY_PATH,
    os.path.join(_LEGACY_DIR, "claudewatch-summaries.json"): SUMMARIES_PATH,
    os.path.join(_LEGACY_DIR, "claudewatch.log"): LOG_PATH,
}


def ensure_data_dir() -> None:
    """Create the data directory and migrate legacy files if needed."""
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    _migrate_legacy_files()


def _migrate_legacy_files() -> None:
    """Move files from ~/.claude/claudewatch-* to the new data directory."""
    for old, new in _MIGRATIONS.items():
        if os.path.exists(old) and not os.path.exists(new):
            try:
                shutil.move(old, new)
                log.info("migrated %s -> %s", old, new)
            except OSError:
                log.warning("failed to migrate %s", old)
