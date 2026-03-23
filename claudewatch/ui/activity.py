"""Activity feed window — shows what Claude did in a session."""

import os
import re

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBox,
    NSButton,
    NSColor,
    NSFont,
    NSMutableAttributedString,
    NSScrollView,
    NSTextView,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import NSURL, NSMakeRect, NSMakeSize, NSObject, NSRange

from claudewatch.backend.helpers import escape_applescript, run_applescript
from claudewatch.backend.services.activity import ActivityEntry, parse_activity
from claudewatch.backend.services.jsonl import find_most_recent_jsonl, get_session_id_from_path

_W = 750
_H = 500

_windows: dict[str, NSWindow] = {}

# Styles per entry kind
_KIND_CONFIG = {
    "user": {"icon": "❯", "color": NSColor.systemGreenColor(), "label": "You"},
    "assistant": {"icon": "◇", "color": NSColor.systemBlueColor(), "label": "Claude"},
    "tool": {"icon": "⚙", "color": NSColor.systemOrangeColor(), "label": "Tool"},
}
_MONO = NSFont.monospacedSystemFontOfSize_weight_(11.0, 0)
_MONO_BOLD = NSFont.monospacedSystemFontOfSize_weight_(11.0, 0.5)
_MONO_SMALL = NSFont.monospacedSystemFontOfSize_weight_(10.0, 0)


def _get_session_id(cwd: str) -> str:
    """Get the most recent session ID for a CWD."""
    path = find_most_recent_jsonl(cwd)
    return get_session_id_from_path(path) if path else ""


class _ActivityDelegate(NSObject):
    """Handle window close and resume action."""

    _cwd: str = ""

    def windowWillClose_(self, notification: objc.objc_object) -> None:
        _windows.pop(self._cwd, None)

    def openInFinder_(self, sender: objc.objc_object) -> None:
        if os.path.isdir(self._cwd):
            NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(self._cwd))

    def resumeSession_(self, sender: objc.objc_object) -> None:
        sid = _get_session_id(self._cwd)
        if not sid or not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", sid):
            return
        safe_cwd = escape_applescript(self._cwd)
        run_applescript(f'''
            tell application "Terminal"
                activate
                do script "cd \\"{safe_cwd}\\" && claude -r {sid}"
            end tell
        ''')


def _append(attr_str: NSMutableAttributedString, text: str, font: NSFont, color: NSColor) -> None:
    """Append styled text to an attributed string."""
    seg = NSMutableAttributedString.alloc().initWithString_(text)
    r = NSRange(0, len(text))
    seg.addAttribute_value_range_("NSFont", font, r)
    seg.addAttribute_value_range_("NSColor", color, r)
    attr_str.appendAttributedString_(seg)


def _render_timeline(entries: list[ActivityEntry]) -> NSMutableAttributedString:
    """Render the full timeline as a rich attributed string."""
    result = NSMutableAttributedString.alloc().initWithString_("")

    if not entries:
        _append(result, "No activity recorded for this session.\n", _MONO, NSColor.secondaryLabelColor())
        return result

    dim = NSColor.secondaryLabelColor()
    prev_kind = ""

    for entry in entries:
        cfg = _KIND_CONFIG.get(entry.kind, {"icon": "·", "color": dim, "label": entry.kind})

        # Add spacing between different kinds of entries
        if prev_kind and prev_kind != entry.kind:
            _append(result, "\n", _MONO_SMALL, dim)

        # Timestamp (if available)
        if entry.timestamp:
            ts_display = entry.timestamp[11:19] if len(entry.timestamp) > 19 else entry.timestamp  # noqa: PLR2004
            _append(result, f"{ts_display}  ", _MONO_SMALL, NSColor.tertiaryLabelColor())

        # Icon + label
        _append(result, f"{cfg['icon']} ", _MONO_BOLD, cfg["color"])

        # Content: use full detail for user/assistant, summary for tools
        if entry.kind in ("user", "assistant"):
            _append(result, f"{entry.detail}\n", _MONO, NSColor.labelColor())
        else:
            _append(result, f"{entry.summary}\n", _MONO, NSColor.labelColor())

        # Detail line for tools (show the full command/path)
        if entry.kind == "tool" and entry.detail and entry.detail != entry.summary:
            detail_lines = entry.detail.split("\n")
            for dl in detail_lines[1:]:  # skip "Tool: name" which is redundant
                if dl.strip():
                    _append(result, f"           {dl.strip()}\n", _MONO_SMALL, dim)

        prev_kind = entry.kind

    return result


def show_activity(project: str, cwd: str, *, session_active: bool = False) -> None:  # noqa: PLR0915
    """Show (or bring to front) the activity window for a session."""
    if cwd in _windows:
        _windows[cwd].makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        return

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    delegate = _ActivityDelegate.alloc().init()
    delegate._cwd = cwd

    style = (
        NSWindowStyleMaskTitled
        | NSWindowStyleMaskClosable
        | NSWindowStyleMaskResizable
        | NSWindowStyleMaskMiniaturizable
    )
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(200, 200, _W, _H),
        style,
        2,  # NSBackingStoreBuffered
        False,
    )
    short_cwd = "~" + cwd[len(os.path.expanduser("~")) :] if cwd.startswith(os.path.expanduser("~")) else cwd
    window.setTitle_(f"{project} — {short_cwd}")
    window.setDelegate_(delegate)
    window.setReleasedWhenClosed_(False)
    window.setMinSize_(NSMakeSize(400, 300))

    root = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _H))

    # Bottom bar with Resume button
    _bar_h = 40
    bar = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _bar_h))
    bar.setAutoresizingMask_(2)  # flexible width

    sep = NSBox.alloc().initWithFrame_(NSMakeRect(0, _bar_h - 1, _W, 1))
    sep.setBoxType_(2)
    bar.addSubview_(sep)

    finder_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_W - 205, 8, 95, 24))
    finder_btn.setTitle_("Open Folder")
    finder_btn.setBezelStyle_(1)
    finder_btn.setTarget_(delegate)
    finder_btn.setAction_(objc.selector(delegate.openInFinder_, signature=b"v@:@"))
    finder_btn.setAutoresizingMask_(4)
    bar.addSubview_(finder_btn)

    if not session_active:
        resume_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_W - 100, 8, 85, 24))
        resume_btn.setTitle_("Resume")
        resume_btn.setBezelStyle_(1)
        resume_btn.setTarget_(delegate)
        resume_btn.setAction_(objc.selector(delegate.resumeSession_, signature=b"v@:@"))
        resume_btn.setAutoresizingMask_(4)
        bar.addSubview_(resume_btn)

    root.addSubview_(bar)

    # Scrollable text view above the bar
    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, _bar_h, _W, _H - _bar_h))
    scroll.setHasVerticalScroller_(True)
    scroll.setAutoresizingMask_(18)  # flexible width + height

    text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _H - _bar_h))
    text_view.setEditable_(False)
    text_view.setBackgroundColor_(NSColor.textBackgroundColor())
    text_view.setAutoresizingMask_(18)
    text_view.setTextContainerInset_(NSMakeSize(16, 16))

    entries = parse_activity(cwd)
    text_view.textStorage().setAttributedString_(_render_timeline(entries))
    text_view.scrollRangeToVisible_(NSRange(len(text_view.string()), 0))

    scroll.setDocumentView_(text_view)
    root.addSubview_(scroll)

    window.setContentView_(root)

    _windows[cwd] = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
