"""Check GitHub Releases for newer versions of ClaudeWatch."""

import json
import logging
import subprocess
import threading
import time

from claudewatch import __version__

log = logging.getLogger("claudewatch")

_CHECK_INTERVAL = 6 * 60 * 60  # 6 hours

_cache_lock = threading.Lock()
_cached_update: dict[str, str] | None = None  # {"tag": "v0.6.0"} or None
_last_check: float = 0.0


def _parse_version(tag: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' or '1.2.3' into (1, 2, 3)."""
    stripped = tag.lstrip("v")
    # Ignore pre-release suffixes for comparison
    base = stripped.split("-")[0]
    try:
        return tuple(int(x) for x in base.split("."))
    except ValueError:
        return (0,)


def _fetch_latest_tag() -> str | None:
    """Fetch the latest release tag from GitHub. Returns tag string or None."""
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["gh", "api", "repos/wingatethomas/claudewatch/releases/latest", "--jq", ".tag_name"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: curl the public API
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["curl", "-sf", "--max-time", "10",
             "https://api.github.com/repos/wingatethomas/claudewatch/releases/latest"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("tag_name")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass

    return None


def check_for_update() -> dict[str, str] | None:
    """Check for a newer release. Updates module cache. Safe to call from any thread."""
    global _cached_update, _last_check  # noqa: PLW0603

    now = time.time()
    with _cache_lock:
        if now - _last_check < _CHECK_INTERVAL:
            return _cached_update

    tag = _fetch_latest_tag()
    if not tag:
        with _cache_lock:
            _last_check = now
        return None

    current = _parse_version(__version__)
    latest = _parse_version(tag)

    with _cache_lock:
        _last_check = now
        if latest > current:
            _cached_update = {"tag": tag}
            log.info("update available: %s (current: %s)", tag, __version__)
        else:
            _cached_update = None

    return _cached_update


def get_cached_update() -> dict[str, str] | None:
    """Return the cached update info without hitting the network."""
    with _cache_lock:
        return _cached_update
