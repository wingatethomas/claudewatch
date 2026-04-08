"""Git remote resolver — maps CWDs to canonical project identity."""

from __future__ import annotations

import logging
import re
import subprocess

log = logging.getLogger("claudewatch")

# SSH:   git@github.com:org/repo.git
_SSH_PATTERN = re.compile(r"^[\w.-]+@[\w.-]+:(.+?)(?:\.git)?$")
# HTTPS: https://github.com/org/repo.git
_HTTPS_PATTERN = re.compile(r"^https?://[^/]+/(.+?)(?:\.git)?$")
# SSH with protocol: ssh://git@gitlab.com/org/repo.git
_SSH_PROTO_PATTERN = re.compile(r"^ssh://[^/]+/(.+?)(?:\.git)?$")


def resolve_remote(cwd: str) -> tuple[str, str, str] | None:
    """Resolve CWD to (remote_url, canonical_name, display_name).

    Returns None if not a git repo or no remote configured.
    """
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],  # noqa: S603, S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    if not url:
        return None
    canonical = parse_remote_url(url)
    display = canonical.split("/")[-1] if "/" in canonical else canonical
    return url, canonical, display


def parse_remote_url(url: str) -> str:
    """Extract org/repo from a git remote URL.

    Handles SSH, HTTPS, and SSH-with-protocol formats.
    Returns the URL as-is if no pattern matches.
    """
    for pattern in (_SSH_PATTERN, _HTTPS_PATTERN, _SSH_PROTO_PATTERN):
        match = pattern.match(url)
        if match:
            return match.group(1)
    return url
