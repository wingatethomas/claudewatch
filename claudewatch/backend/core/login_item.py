"""Login item management — add/remove ClaudeWatch from macOS login items.

Uses a LaunchAgent plist in ~/Library/LaunchAgents/ to auto-start on login.
"""

import logging
import os
import plistlib
import sys

from claudewatch.backend.core.features import Facet, FacetType, Feature, register

log = logging.getLogger("claudewatch")

register(Feature(key="launch_at_login", description="Launch at login", default_enabled=False))
register(
    Feature(
        key="accessibility",
        description="Accessibility",
        default_enabled=True,
        facets=(
            Facet(
                name="color_scheme",
                type=FacetType.CHOICE,
                default="Default",
                description="Status colors",
                options=("Default", "Blue-Orange", "Blue-Yellow", "High Contrast"),
            ),
        ),
    )
)

_PLIST_NAME = "com.claudewatch.plist"
_LAUNCH_AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")
_PLIST_PATH = os.path.join(_LAUNCH_AGENTS_DIR, _PLIST_NAME)


def _get_app_path() -> str:
    """Get the path to the ClaudeWatch executable."""
    # If running as a .app bundle, use the bundle path
    exe = sys.executable
    # Briefcase bundles: /Applications/ClaudeWatch.app/Contents/MacOS/ClaudeWatch
    app_idx = exe.find(".app/")
    if app_idx > 0:
        return exe[: app_idx + 4] + "/Contents/MacOS/ClaudeWatch"
    # Running from source: use the same command that started us
    return exe


def is_login_item() -> bool:
    """Check if ClaudeWatch is registered as a login item."""
    return os.path.isfile(_PLIST_PATH)


def add_login_item() -> bool:
    """Add ClaudeWatch as a login item. Returns True on success."""
    app_path = _get_app_path()
    plist = {
        "Label": "com.claudewatch",
        "ProgramArguments": [app_path],
        "RunAtLoad": True,
        "KeepAlive": False,
    }
    try:
        os.makedirs(_LAUNCH_AGENTS_DIR, exist_ok=True)
        with open(_PLIST_PATH, "wb") as f:
            plistlib.dump(plist, f)
        log.info("login_item.added path=%s", _PLIST_PATH)
        return True
    except OSError:
        log.warning("login_item.add_failed path=%s", _PLIST_PATH)
        return False


def remove_login_item() -> bool:
    """Remove ClaudeWatch from login items. Returns True on success."""
    try:
        if os.path.isfile(_PLIST_PATH):
            os.remove(_PLIST_PATH)
            log.info("login_item.removed path=%s", _PLIST_PATH)
        return True
    except OSError:
        log.warning("login_item.remove_failed path=%s", _PLIST_PATH)
        return False


def sync_login_item(enabled: bool) -> None:
    """Sync login item state to match the feature toggle."""
    if enabled:
        add_login_item()
    else:
        remove_login_item()


def refresh_login_item() -> None:
    """If launch_at_login is active, ensure the plist points to the current binary.

    Fixes stale plists after Homebrew upgrades move the app bundle.
    Called on every launch from main().
    """
    if not os.path.isfile(_PLIST_PATH):
        return

    try:
        with open(_PLIST_PATH, "rb") as f:
            plist = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException):
        log.warning("login_item.refresh: could not read plist")
        return

    stored_args = plist.get("ProgramArguments", [])
    stored_path = stored_args[0] if stored_args else ""
    current_path = _get_app_path()

    if stored_path == current_path:
        return

    log.info("login_item.refresh: updating path from %s to %s", stored_path, current_path)
    add_login_item()
