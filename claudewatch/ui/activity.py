"""Activity feed window — shows what Claude did in a session."""

import os
import re
import subprocess

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBox,
    NSButton,
    NSColor,
    NSFont,
    NSMutableAttributedString,
    NSPasteboard,
    NSPasteboardTypeString,
    NSScrollView,
    NSTextView,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSMakeSize, NSObject, NSRange

from claudewatch.backend.activity.dependencies import get_activity_service
from claudewatch.backend.core.dto import ActivityEventDTO
from claudewatch.backend.core.helpers import escape_applescript, run_applescript
from claudewatch.backend.core.session_log.dependencies import get_session_log_service

_W = 750
_H = 500

_windows: dict[str, NSWindow] = {}
_text_views: dict[str, NSTextView] = {}
_sort_state: dict[str, bool] = {}  # CWD → newest_first

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
    svc = get_session_log_service()
    path = svc.find_most_recent(cwd)
    return svc.get_session_id(path) if path else ""


class _ActivityDelegate(NSObject):
    """Handle window close, resume, and sort actions."""

    _cwd: str = ""

    def windowWillClose_(self, notification: objc.objc_object) -> None:
        _windows.pop(self._cwd, None)
        _text_views.pop(self._cwd, None)
        _sort_state.pop(self._cwd, None)

    def openInFinder_(self, sender: objc.objc_object) -> None:
        if self._cwd and os.path.isdir(self._cwd):
            subprocess.run(["open", self._cwd], check=False)  # noqa: S603, S607

    def copyToClipboard_(self, sender: objc.objc_object) -> None:
        tv = _text_views.get(self._cwd)
        if tv:
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(tv.string(), NSPasteboardTypeString)

    def openJsonlInFinder_(self, sender: objc.objc_object) -> None:
        path = get_session_log_service().find_most_recent(self._cwd)
        if path:
            subprocess.run(["open", "-R", path], check=False)  # noqa: S603, S607

    def toggleSort_(self, sender: objc.objc_object) -> None:
        newest_first = not _sort_state.get(self._cwd, False)
        _sort_state[self._cwd] = newest_first
        sender.setTitle_("↓ Newest first" if newest_first else "↑ Oldest first")
        entries = get_activity_service().parse(self._cwd)
        if newest_first:
            entries = list(reversed(entries))
        tv = _text_views.get(self._cwd)
        if tv is not None:
            tv.textStorage().setAttributedString_(_render_timeline(entries))
            if newest_first:
                tv.scrollRangeToVisible_(NSRange(0, 0))
            else:
                tv.scrollRangeToVisible_(NSRange(len(tv.string()), 0))

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


def _render_timeline(entries: list[ActivityEventDTO]) -> NSMutableAttributedString:
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

    sort_btn = NSButton.alloc().initWithFrame_(NSMakeRect(12, 8, 110, 24))
    sort_btn.setTitle_("↑ Oldest first")
    sort_btn.setFont_(NSFont.systemFontOfSize_(11.0))
    sort_btn.setBezelStyle_(1)
    sort_btn.setTarget_(delegate)
    sort_btn.setAction_(objc.selector(delegate.toggleSort_, signature=b"v@:@"))
    bar.addSubview_(sort_btn)

    copy_btn = NSButton.alloc().initWithFrame_(NSMakeRect(128, 8, 60, 24))
    copy_btn.setTitle_("Copy")
    copy_btn.setBezelStyle_(1)
    copy_btn.setToolTip_("Copy activity to clipboard")
    copy_btn.setTarget_(delegate)
    copy_btn.setAction_(objc.selector(delegate.copyToClipboard_, signature=b"v@:@"))
    bar.addSubview_(copy_btn)

    jsonl_btn = NSButton.alloc().initWithFrame_(NSMakeRect(194, 8, 95, 24))
    jsonl_btn.setTitle_("Session File")
    jsonl_btn.setBezelStyle_(1)
    jsonl_btn.setToolTip_("Reveal session log in Finder")
    jsonl_btn.setTarget_(delegate)
    jsonl_btn.setAction_(objc.selector(delegate.openJsonlInFinder_, signature=b"v@:@"))
    bar.addSubview_(jsonl_btn)

    finder_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_W - 210, 8, 100, 24))
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

    _text_views[cwd] = text_view
    entries = get_activity_service().parse(cwd)
    text_view.textStorage().setAttributedString_(_render_timeline(entries))
    text_view.scrollRangeToVisible_(NSRange(len(text_view.string()), 0))

    scroll.setDocumentView_(text_view)
    root.addSubview_(scroll)

    window.setContentView_(root)

    _windows[cwd] = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
