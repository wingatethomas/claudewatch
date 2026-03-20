"""Activity feed window — shows what Claude did in a session."""

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSColor,
    NSFont,
    NSMutableAttributedString,
    NSScrollView,
    NSTextView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSMakeSize, NSObject, NSRange

from claudewatch.backend.services.activity import ActivityEntry, parse_activity

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


class _ActivityDelegate(NSObject):
    """Handle window close to clean up tracking."""

    _cwd: str = ""

    def windowWillClose_(self, notification: objc.objc_object) -> None:
        _windows.pop(self._cwd, None)


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

        # Summary
        _append(result, f"{entry.summary}\n", _MONO, NSColor.labelColor())

        # Detail line for tools (show the full command/path)
        if entry.kind == "tool" and entry.detail and entry.detail != entry.summary:
            detail_lines = entry.detail.split("\n")
            for dl in detail_lines[1:]:  # skip "Tool: name" which is redundant
                if dl.strip():
                    _append(result, f"           {dl.strip()}\n", _MONO_SMALL, dim)

        prev_kind = entry.kind

    return result


def show_activity(project: str, cwd: str) -> None:
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
    window.setTitle_(f"{project} — Activity")
    window.setDelegate_(delegate)
    window.setReleasedWhenClosed_(False)
    window.setMinSize_(NSMakeSize(400, 300))

    # Scrollable text view
    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _H))
    scroll.setHasVerticalScroller_(True)
    scroll.setAutoresizingMask_(18)  # flexible width + height

    text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _H))
    text_view.setEditable_(False)
    text_view.setBackgroundColor_(NSColor.textBackgroundColor())
    text_view.setAutoresizingMask_(18)
    text_view.setTextContainerInset_(NSMakeSize(16, 16))

    # Parse and render
    entries = parse_activity(cwd)
    text_view.textStorage().setAttributedString_(_render_timeline(entries))

    # Scroll to bottom (newest)
    text_view.scrollRangeToVisible_(NSRange(len(text_view.string()), 0))

    scroll.setDocumentView_(text_view)
    window.setContentView_(scroll)

    _windows[cwd] = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
