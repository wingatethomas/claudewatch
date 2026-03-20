"""Activity feed window — shows what Claude did in a session."""

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSColor,
    NSFont,
    NSScrollView,
    NSTextView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSMakeSize, NSObject

from claudewatch.backend.services.activity import ActivityEntry, parse_activity

_W = 500
_H = 450

# Track open windows by CWD to avoid duplicates
_windows: dict[str, NSWindow] = {}


class _ActivityDelegate(NSObject):
    """Handle window close to clean up tracking."""

    _cwd: str = ""

    def windowWillClose_(self, notification: objc.objc_object) -> None:
        _windows.pop(self._cwd, None)


def _format_entry(entry: ActivityEntry) -> str:
    """Format a single activity entry as styled text."""
    icons = {"user": "❯", "assistant": "◇", "tool": "⚙", "thinking": "…"}
    icon = icons.get(entry.kind, "·")
    return f"{icon}  {entry.summary}"


def _render_timeline(entries: list[ActivityEntry]) -> str:
    """Render the full timeline as plain text."""
    if not entries:
        return "No activity recorded for this session."
    lines = []
    for entry in entries:
        lines.append(_format_entry(entry))
    return "\n".join(lines)


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
    window.setMinSize_(NSMakeSize(350, 250))

    # Scrollable text view
    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _H))
    scroll.setHasVerticalScroller_(True)
    scroll.setAutoresizingMask_(18)  # flexible width + height

    text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _H))
    text_view.setEditable_(False)
    text_view.setFont_(NSFont.monospacedSystemFontOfSize_weight_(12.0, 0))
    text_view.setTextColor_(NSColor.labelColor())
    text_view.setBackgroundColor_(NSColor.textBackgroundColor())
    text_view.setAutoresizingMask_(18)
    text_view.setTextContainerInset_(NSMakeSize(12, 12))

    # Parse and render activity
    entries = parse_activity(cwd)
    text_view.setString_(_render_timeline(entries))

    scroll.setDocumentView_(text_view)
    window.setContentView_(scroll)

    _windows[cwd] = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
