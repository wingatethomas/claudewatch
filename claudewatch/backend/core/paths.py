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
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")  # Legacy — kept for migration only
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


_HOMEBREW_CASKROOM = "/opt/homebrew/Caskroom/claudewatch"
_HOMEBREW_CASKROOM_INTEL = "/usr/local/Caskroom/claudewatch"


def is_homebrew_install() -> bool:
    """Check if ClaudeWatch was installed via Homebrew."""
    return os.path.isdir(_HOMEBREW_CASKROOM) or os.path.isdir(_HOMEBREW_CASKROOM_INTEL)


CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")


def cwd_to_proj_key(cwd: str) -> str:
    """Convert a CWD path to a Claude projects directory key.

    Example: '/Users/dev/myapp' -> '-Users-dev-myapp'
    """
    return cwd.replace("/", "-")


def proj_key_to_cwd(proj_key: str) -> str:
    """Reverse cwd_to_proj_key by validating against the filesystem.

    The key replaces all '/' with '-', making it ambiguous when directory
    names contain hyphens. We resolve this by building the path segment
    by segment, checking which combinations exist on disk.

    Example: '-Users-dev-backend-api' -> '/Users/dev/backend-api'
    """
    if not proj_key.startswith("-"):
        return proj_key.replace("-", "/", 1)

    parts = proj_key[1:].split("-")
    return _resolve_path_segments(parts)


def _resolve_path_segments(parts: list[str]) -> str:
    """Build a filesystem path from hyphen-split segments.

    Uses a longest-match approach: when multiple hyphen-joined combinations
    exist on disk, picks the longest one to avoid incorrect splits.
    e.g. 'backend-api-auth-rework' is preferred over 'backend-api' + 'auth/rework'.
    """
    if not parts:
        return "/"

    path = "/" + parts[0]
    i = 1
    while i < len(parts):
        # Try all possible hyphen-joined combinations, longest first
        best_candidate = ""
        best_j = -1
        accumulated = parts[i]
        for j in range(i + 1, len(parts) + 1):
            candidate = path + "/" + accumulated
            if os.path.exists(candidate):
                best_candidate = candidate
                best_j = j
            if j < len(parts):
                accumulated += "-" + parts[j]
        if best_j > 0:
            path = best_candidate
            i = best_j
        else:
            # Nothing matched — default to slash
            path = path + "/" + parts[i]
            i += 1
    return path
