import ctypes
import logging

from Foundation import NSAppleScript

log = logging.getLogger("claudewatch")


def is_accessibility_trusted() -> bool:
    """Check if the app has Accessibility permissions via AXIsProcessTrusted."""
    try:
        lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return lib.AXIsProcessTrusted()
    except OSError:
        return False


def run_applescript(source: str) -> str:
    script = NSAppleScript.alloc().initWithSource_(source)
    result, error = script.executeAndReturnError_(None)
    if error:
        msg = error.get("NSAppleScriptErrorMessage", error)
        if "-60005" in str(msg):
            log.warning("AppleScript error (Accessibility permissions required): %s", msg)
        else:
            log.debug("AppleScript error: %s", msg)
    return result.stringValue() or "" if result else ""


def escape_applescript(s: str) -> str:
    """Escape a string for safe interpolation into AppleScript double-quoted literals.

    Handles backslashes, double quotes, and strips control characters
    (e.g. \\r, \\n) that could break out of an AppleScript string literal.
    """
    # Strip control characters (keep printable + tab)
    s = "".join(c for c in s if c >= " " or c == "\t")
    return s.replace("\\", "\\\\").replace('"', '\\"')
