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
from claudewatch.backend.detection.dependencies import get_detection_service
from claudewatch.ui.components.tokens import Font
from claudewatch.ui.focus import focus_session
from claudewatch.ui.safety import objc_callback

_W = 750
_H = 500

# All dicts keyed by "{cwd}::{session_id}" so sessions sharing a cwd get separate windows
_windows: dict[str, NSWindow] = {}
_delegates: dict[str, object] = {}  # prevent GC of delegate
_text_views: dict[str, NSTextView] = {}
_sort_state: dict[str, bool] = {}  # key → newest_first

# Styles per entry kind
_KIND_CONFIG = {
    "user": {"icon": "❯", "color": NSColor.systemGreenColor(), "label": "You"},
    "assistant": {"icon": "◇", "color": NSColor.systemBlueColor(), "label": "Claude"},
    "tool": {"icon": "⚙", "color": NSColor.systemOrangeColor(), "label": "Tool"},
    "recap": {"icon": "✻", "color": NSColor.systemPurpleColor(), "label": "Recap"},
}
_MONO = NSFont.monospacedSystemFontOfSize_weight_(Font.SMALL, 0)
_MONO_BOLD = NSFont.monospacedSystemFontOfSize_weight_(Font.SMALL, 0.5)
_MONO_SMALL = NSFont.monospacedSystemFontOfSize_weight_(Font.CAPTION, 0)


def _get_session_id(cwd: str) -> str:
    """Get the most recent session ID for a CWD."""
    svc = get_session_log_service()
    path = svc.find_most_recent(cwd)
    return svc.get_session_id(path) if path else ""


class _ActivityDelegate(NSObject):
    """Handle window close, resume, and sort actions."""

    _cwd: str = ""
    _session_id: str = ""
    _key: str = ""

    @objc_callback
    def windowWillClose_(self, notification: objc.objc_object) -> None:
        _windows.pop(self._key, None)
        _delegates.pop(self._key, None)
        _text_views.pop(self._key, None)
        _sort_state.pop(self._key, None)

    @objc_callback
    def openInFinder_(self, sender: objc.objc_object) -> None:
        if self._cwd and os.path.isdir(self._cwd):
            subprocess.run(["open", self._cwd], check=False)  # noqa: S603, S607

    @objc_callback
    def copyToClipboard_(self, sender: objc.objc_object) -> None:
        tv = _text_views.get(self._key)
        if tv:
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(tv.string(), NSPasteboardTypeString)

    @objc_callback
    def openJsonlInFinder_(self, sender: objc.objc_object) -> None:
        path = get_session_log_service().resolve_jsonl(self._cwd, self._session_id)
        if path:
            subprocess.run(["open", "-R", path], check=False)  # noqa: S603, S607

    @objc_callback
    def toggleSort_(self, sender: objc.objc_object) -> None:
        newest_first = not _sort_state.get(self._key, False)
        _sort_state[self._key] = newest_first
        sender.setTitle_("↓ Newest first" if newest_first else "↑ Oldest first")
        entries = get_activity_service().parse(self._cwd, self._session_id)
        if newest_first:
            entries = list(reversed(entries))
        tv = _text_views.get(self._key)
        if tv is not None:
            tv.textStorage().setAttributedString_(_render_timeline(entries))
            if newest_first:
                tv.scrollRangeToVisible_(NSRange(0, 0))
            else:
                tv.scrollRangeToVisible_(NSRange(len(tv.string()), 0))

    @objc_callback
    def focusSession_(self, sender: objc.objc_object) -> None:  # noqa: N802
        sessions = get_detection_service().detect()
        match = next((s for s in sessions if self._session_id and s.session_id == self._session_id), None)
        if match is None:
            match = next((s for s in sessions if s.cwd == self._cwd), None)
        if match is not None:
            focus_session(match)

    @objc_callback
    def resumeSession_(self, sender: objc.objc_object) -> None:
        sid = self._session_id or _get_session_id(self._cwd)
        if not sid or not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", sid):
            return
        safe_cwd = escape_applescript(self._cwd)
        run_applescript(f'''
            do shell script "open -a Terminal \\"{safe_cwd}\\""
            delay 0.5
            tell application "Terminal"
                do script "claude -r {sid}" in front window
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


def show_activity(project: str, cwd: str, session_id: str = "", *, session_active: bool = False) -> None:  # noqa: PLR0915
    """Show (or bring to front) the activity window for a session."""
    key = f"{cwd}::{session_id}"
    if key in _windows:
        _windows[key].makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        return

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    delegate = _ActivityDelegate.alloc().init()
    delegate._cwd = cwd
    delegate._session_id = session_id
    delegate._key = key

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

    _btn_h = 24
    _btn_font = NSFont.systemFontOfSize_(11.0)
    _gap = 8
    _left_x = 12

    def _bar_btn(x: float, title: str, action: object, tip: str = "", *, auto_right: bool = False) -> NSButton:
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, 8, 140, _btn_h))
        btn.setTitle_(title)
        btn.setFont_(_btn_font)
        btn.setBezelStyle_(1)
        btn.setTarget_(delegate)
        btn.setAction_(action)
        if tip:
            btn.setToolTip_(tip)
        if auto_right:
            btn.setAutoresizingMask_(4)  # pin to right edge
        bar.addSubview_(btn)
        return btn

    _bw = 140  # uniform button width
    _bar_btn(_left_x, "↑ Oldest first", objc.selector(delegate.toggleSort_, signature=b"v@:@"))
    _bar_btn(
        _left_x + _bw + _gap,
        "Copy",
        objc.selector(delegate.copyToClipboard_, signature=b"v@:@"),
        "Copy activity to clipboard",
    )
    _bar_btn(
        _left_x + (_bw + _gap) * 2,
        "View Session JSON",
        objc.selector(delegate.openJsonlInFinder_, signature=b"v@:@"),
        "Reveal session JSONL in Finder",
    )
    _bar_btn(
        _W - _bw - _gap - _bw - 12,
        "Open Project in Finder",
        objc.selector(delegate.openInFinder_, signature=b"v@:@"),
        "Open project folder in Finder",
        auto_right=True,
    )

    if session_active:
        _bar_btn(
            _W - _bw - 12,
            "Focus",
            objc.selector(delegate.focusSession_, signature=b"v@:@"),
            "Switch to session window",
            auto_right=True,
        )
    else:
        _bar_btn(
            _W - _bw - 12,
            "Resume",
            objc.selector(delegate.resumeSession_, signature=b"v@:@"),
            "Resume session in Terminal",
            auto_right=True,
        )

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

    _text_views[key] = text_view
    entries = get_activity_service().parse(cwd, session_id)
    text_view.textStorage().setAttributedString_(_render_timeline(entries))
    text_view.scrollRangeToVisible_(NSRange(len(text_view.string()), 0))

    scroll.setDocumentView_(text_view)
    root.addSubview_(scroll)

    window.setContentView_(root)

    _delegates[key] = delegate
    _windows[key] = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
