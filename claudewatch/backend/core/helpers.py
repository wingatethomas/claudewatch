import logging
import subprocess

from Foundation import NSAppleScript

log = logging.getLogger("claudewatch")


def _shell(cmd: str) -> str:
    """Run a shell command and return stdout. Internal use only — callers must ensure
    all interpolated values are validated (e.g. integer PIDs from isdigit() checks)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5, check=False)  # noqa: S602
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def run_applescript(source: str) -> str:
    script = NSAppleScript.alloc().initWithSource_(source)
    result, error = script.executeAndReturnError_(None)
    if error:
        log.debug("AppleScript error: %s", error.get("NSAppleScriptErrorMessage", error))
    return result.stringValue() or "" if result else ""


def escape_applescript(s: str) -> str:
    """Escape a string for safe interpolation into AppleScript double-quoted literals.

    Handles backslashes, double quotes, and strips control characters
    (e.g. \\r, \\n) that could break out of an AppleScript string literal.
    """
    # Strip control characters (keep printable + tab)
    s = "".join(c for c in s if c >= " " or c == "\t")
    return s.replace("\\", "\\\\").replace('"', '\\"')
