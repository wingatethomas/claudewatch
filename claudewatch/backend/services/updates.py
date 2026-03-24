"""Check GitHub Releases for newer versions of ClaudeWatch."""

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable

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


_REPO = "wingatethomas/claudewatch"


def _get_download_url(tag: str) -> str:
    """Build the release asset URL for a given tag."""
    return f"https://github.com/{_REPO}/releases/download/{tag}/ClaudeWatch-{tag}-arm64.zip"


def _find_app_bundle() -> str | None:
    """Find the running .app bundle path, if running from one."""
    # When running as a .app, sys.executable is inside the bundle:
    # ClaudeWatch.app/Contents/MacOS/ClaudeWatch
    exe = os.path.realpath(sys.executable)
    parts = exe.split("/")
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            return "/".join(parts[: i + 1])
    return None


def download_and_apply_update(tag: str, on_ready: Callable[[], None] | None = None) -> bool:
    """Download a release and prepare the swap. Returns True if swap is staged.

    Call on_ready() (which should quit the app) after staging succeeds.
    The swap script runs after the app exits.
    """
    app_path = _find_app_bundle()
    if not app_path:
        log.warning("update: not running from a .app bundle, cannot self-update")
        return False

    url = _get_download_url(tag)
    tmp_dir = tempfile.mkdtemp(prefix="claudewatch-update-")
    zip_path = os.path.join(tmp_dir, "update.zip")

    log.info("update: downloading %s", url)
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["curl", "-fSL", "--max-time", "60", "-o", zip_path, url],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if result.returncode != 0:
            log.warning("update: download failed: %s", result.stderr.strip())
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("update: download failed: %s", e)
        return False

    # Unzip
    extract_dir = os.path.join(tmp_dir, "extracted")
    os.makedirs(extract_dir)
    try:
        subprocess.run(  # noqa: S603, S607
            ["unzip", "-q", zip_path, "-d", extract_dir],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("update: unzip failed: %s", e)
        return False

    # Find the .app inside the extracted directory
    new_app = None
    for name in os.listdir(extract_dir):
        if name.endswith(".app"):
            new_app = os.path.join(extract_dir, name)
            break
    if not new_app:
        log.warning("update: no .app found in zip")
        return False

    # Stage the swap script — runs after our process exits
    pid = os.getpid()
    script = f"""#!/bin/bash
# Wait for ClaudeWatch to exit (max 30s)
for i in $(seq 1 60); do
    kill -0 {pid} 2>/dev/null || break
    sleep 0.5
done
# Swap the app bundle
rm -rf "{app_path}"
mv "{new_app}" "{app_path}"
# Relaunch
open "{app_path}"
# Cleanup
rm -rf "{tmp_dir}"
"""
    script_path = os.path.join(tmp_dir, "swap.sh")
    with open(script_path, "w") as f:
        f.write(script)
    os.chmod(script_path, 0o755)  # noqa: S103

    # Launch the swap script detached from our process
    subprocess.Popen(  # noqa: S603
        [script_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    log.info("update: swap script staged, quitting for update to %s", tag)

    if on_ready:
        on_ready()
    return True
