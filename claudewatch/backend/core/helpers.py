import ctypes
import json
import logging
import os
import threading

from Foundation import NSAppleScript

log = logging.getLogger("claudewatch")

_APPLESCRIPT_TIMEOUT = 10.0


def atomic_json_write(path: str, data: object, *, indent: int | None = 2) -> None:
    """Write JSON to ``path`` atomically: serialize to ``path + ".tmp"``, then rename.

    A crash mid-write leaves ``path`` either unchanged or fully replaced — never
    a half-written file. Raises ``OSError`` on filesystem failure; callers wrap
    with their domain-specific log message.
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=indent)
    os.replace(tmp, path)


def is_accessibility_trusted() -> bool:
    """Check if the app has Accessibility permissions via AXIsProcessTrusted."""
    try:
        lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return lib.AXIsProcessTrusted()
    except OSError:
        return False


def run_applescript(source: str, *, timeout: float = _APPLESCRIPT_TIMEOUT) -> str:
    """Execute AppleScript with a timeout. Returns empty string on timeout or error."""
    result_holder: list[str] = []

    def _execute() -> None:
        script = NSAppleScript.alloc().initWithSource_(source)
        result, error = script.executeAndReturnError_(None)
        if error:
            msg = error.get("NSAppleScriptErrorMessage", error)
            if "-60005" in str(msg):
                log.warning("AppleScript error (Accessibility permissions required): %s", msg)
            else:
                log.debug("AppleScript error: %s", msg)
        result_holder.append(result.stringValue() or "" if result else "")

    thread = threading.Thread(target=_execute, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        log.warning("AppleScript timed out after %.0fs", timeout)
        return ""
    return result_holder[0] if result_holder else ""


def escape_applescript(s: str) -> str:
    """Escape a string for safe interpolation into AppleScript double-quoted literals.

    Handles backslashes, double quotes, and strips control characters
    (e.g. \\r, \\n) that could break out of an AppleScript string literal.
    """
    # Strip control characters (keep printable + tab)
    s = "".join(c for c in s if c >= " " or c == "\t")
    return s.replace("\\", "\\\\").replace('"', '\\"')
