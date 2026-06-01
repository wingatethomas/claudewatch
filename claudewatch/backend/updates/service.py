"""Check GitHub Releases for newer versions of ClaudeWatch."""

from __future__ import annotations

import hashlib
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
from claudewatch.backend.core import features
from claudewatch.backend.core.dto import ChangelogEntryDTO, UpdateInfoDTO
from claudewatch.backend.core.features import FeatureKey
from claudewatch.backend.core.service import BaseService

log = logging.getLogger("claudewatch")

_CHECK_INTERVAL = 6 * 60 * 60  # 6 hours

_REPO = "wingatethomas/claudewatch"


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
            [
                "curl",
                "-sf",
                "--max-time",
                "10",
                "https://api.github.com/repos/wingatethomas/claudewatch/releases/latest",
            ],
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


def _get_download_url(tag: str) -> str:
    """Build the release asset URL for a given tag."""
    return f"https://github.com/{_REPO}/releases/download/{tag}/ClaudeWatch-{tag}-arm64.zip"


def _sha256_file(path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_expected_checksum(tag: str) -> str | None:
    """Fetch SHA-256 checksum from the release's checksums.txt asset."""
    url = f"https://github.com/{_REPO}/releases/download/{tag}/checksums.txt"
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["curl", "-sfL", "--max-time", "10", url],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                if "arm64.zip" in line:
                    return line.split()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


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


class UpdateService(BaseService):
    """Checks GitHub Releases for newer versions and applies self-updates."""

    def __init__(self) -> None:
        super().__init__()
        self._cache_lock = threading.Lock()
        self._cached_update: UpdateInfoDTO | None = None
        self._last_check: float = 0.0

    def check(self) -> UpdateInfoDTO | None:
        """Check for a newer release. Updates instance cache. Thread-safe."""
        if not features.is_enabled(FeatureKey.AUTO_UPDATES):
            return None
        now = time.time()
        with self._cache_lock:
            if now - self._last_check < _CHECK_INTERVAL:
                return self._cached_update

        tag = _fetch_latest_tag()
        if not tag:
            with self._cache_lock:
                self._last_check = now
            return None

        current = _parse_version(__version__)
        latest = _parse_version(tag)

        with self._cache_lock:
            self._last_check = now
            if latest > current:
                self._cached_update = UpdateInfoDTO(
                    tag=tag,
                    download_url=_get_download_url(tag),
                )
                log.info("update available: %s (current: %s)", tag, __version__)
            else:
                self._cached_update = None

        return self._cached_update

    def get_cached(self) -> UpdateInfoDTO | None:
        """Return the cached update info without hitting the network."""
        with self._cache_lock:
            return self._cached_update

    def fetch_changelog(self, limit: int = 10) -> list[ChangelogEntryDTO]:
        """Fetch recent release notes from GitHub. Returns list of ChangelogEntryDTO."""
        try:
            result = subprocess.run(  # noqa: S603, S607
                [
                    "curl",
                    "-sf",
                    "--max-time",
                    "10",
                    f"https://api.github.com/repos/{_REPO}/releases?per_page={limit}",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode == 0:
                releases = json.loads(result.stdout)
                return [
                    ChangelogEntryDTO(tag=r.get("tag_name", ""), body=r.get("body", "").strip())
                    for r in releases
                    if r.get("tag_name") and not r.get("prerelease")
                ]
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        return []

    def download_and_apply(self, tag: str, on_ready: Callable[[], None] | None = None) -> bool:  # noqa: PLR0911
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

        # Checksum verification is mandatory. If the release doesn't expose a
        # readable checksums.txt, refuse to install — an attacker who can block
        # just the checksum fetch shouldn't be able to skip verification.
        expected = _fetch_expected_checksum(tag)
        if not expected:
            log.warning("update: no checksum available for %s — refusing to install", tag)
            return False
        actual = _sha256_file(zip_path)
        if actual != expected:
            log.warning("update: checksum mismatch — expected %s, got %s", expected[:12], actual[:12])
            return False
        log.info("update: checksum verified")

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
        os.chmod(script_path, 0o755)  # noqa: S103  # nosec B103 - intentional exec bit on our own swap script

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
