"""First-launch welcome window — full transparency on what ClaudeWatch does."""

import subprocess

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBox,
    NSButton,
    NSColor,
    NSFont,
    NSObject,
    NSScrollView,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect

from claudewatch.backend.repositories.config import get_setting, set_setting

_W = 560
_H = 620

_window: NSWindow | None = None
_delegate: "_WelcomeDelegate | None" = None


class _WelcomeDelegate(NSObject):
    def windowWillClose_(self, notification: object) -> None:  # noqa: N802, ARG002
        global _window, _delegate  # noqa: PLW0603
        _window = None
        _delegate = None

    def openAccessibility_(self, sender: object) -> None:  # noqa: N802, ARG002
        subprocess.run(  # noqa: S603, S607
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            check=False,
        )

    def openAutomation_(self, sender: object) -> None:  # noqa: N802, ARG002
        subprocess.run(  # noqa: S603, S607
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"],
            check=False,
        )

    def dismiss_(self, sender: object) -> None:  # noqa: N802, ARG002
        if _window:
            _window.close()


# ── Layout helpers ───────────────────────────────────────────────────

_INSET = 28
_CONTENT_W = _W - _INSET * 2


def _heading(view: NSView, text: str, y: int) -> int:
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(_INSET, y, _CONTENT_W, 18))
    label.setFont_(NSFont.boldSystemFontOfSize_(13.0))
    label.setTextColor_(NSColor.labelColor())
    view.addSubview_(label)
    return y - 20


def _body(view: NSView, text: str, y: int) -> int:
    label = NSTextField.wrappingLabelWithString_(text)
    label.setFrame_(NSMakeRect(_INSET + 12, y, _CONTENT_W - 12, 200))
    label.setFont_(NSFont.systemFontOfSize_(11.5))
    label.setTextColor_(NSColor.secondaryLabelColor())
    label.sizeToFit()
    h = int(label.frame().size.height)
    label.setFrame_(NSMakeRect(_INSET + 12, y - h + 14, _CONTENT_W - 12, h))
    view.addSubview_(label)
    return y - h - 4


def _separator(view: NSView, y: int) -> int:
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(_INSET, y, _CONTENT_W, 1))
    sep.setBoxType_(2)
    view.addSubview_(sep)
    return y - 12


def _button(view: NSView, title: str, y: int, delegate: _WelcomeDelegate, action: str) -> None:
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(_W - _INSET - 140, y, 130, 24))
    btn.setTitle_(title)
    btn.setBezelStyle_(1)
    btn.setControlSize_(1)  # NSControlSizeSmall
    btn.setFont_(NSFont.systemFontOfSize_(11.0))
    btn.setTarget_(delegate)
    btn.setAction_(objc.selector(getattr(delegate, action), signature=b"v@:@"))
    view.addSubview_(btn)


# ── Public API ───────────────────────────────────────────────────────


def should_show_welcome() -> bool:
    """Check if the welcome window has been shown before."""
    return not get_setting("welcome_shown")


def show_welcome() -> None:  # noqa: PLR0915
    """Show the first-launch welcome window."""
    global _window, _delegate  # noqa: PLW0603

    if _window is not None:
        _window.makeKeyAndOrderFront_(None)
        return

    set_setting("welcome_shown", True)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    app.activateIgnoringOtherApps_(True)

    _delegate = _WelcomeDelegate.alloc().init()

    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(300, 200, _W, _H),
        style,
        2,
        False,
    )
    window.setTitle_("Welcome to ClaudeWatch")
    window.setDelegate_(_delegate)
    window.setReleasedWhenClosed_(False)
    window.center()

    root = window.contentView()

    # ── Scrollable content ───────────────────────────────────────
    # Build content in a tall NSView, wrap in NSScrollView
    content_h = 820  # tall enough for all sections
    content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, content_h))
    y = content_h - 30

    # Title
    title = NSTextField.labelWithString_("Welcome to ClaudeWatch")
    title.setFrame_(NSMakeRect(_INSET, y, _CONTENT_W, 28))
    title.setFont_(NSFont.boldSystemFontOfSize_(20.0))
    title.setTextColor_(NSColor.labelColor())
    content.addSubview_(title)
    y -= 28

    subtitle = NSTextField.wrappingLabelWithString_(
        "ClaudeWatch is a menu bar app that monitors your Claude Code sessions. "
        "Here's exactly what it does and what permissions it needs."
    )
    subtitle.setFrame_(NSMakeRect(_INSET, y - 30, _CONTENT_W, 30))
    subtitle.setFont_(NSFont.systemFontOfSize_(12.0))
    subtitle.setTextColor_(NSColor.secondaryLabelColor())
    content.addSubview_(subtitle)
    y -= 52

    y = _separator(content, y)

    # ── What ClaudeWatch reads ───────────────────────────────────
    y = _heading(content, "What it reads", y)
    y = _body(content, (
        "\u2022 ~/.claude/projects/ \u2014 JSONL session files to detect active sessions, "
        "read conversation history, and extract model/token usage\n"
        "\u2022 ~/Library/Application Support/ClaudeWatch/ \u2014 preferences, pins, history, summaries\n"
        "\u2022 Process table (via libproc) \u2014 finds running Claude Code processes by PID"
    ), y)

    y = _separator(content, y)

    # ── What ClaudeWatch writes ──────────────────────────────────
    y = _heading(content, "What it writes", y)
    y = _body(content, (
        "All written to ~/Library/Application Support/ClaudeWatch/:\n"
        "\u2022 settings.json \u2014 preferences and onboarding state\n"
        "\u2022 pins.json \u2014 pinned session bookmarks\n"
        "\u2022 history.json \u2014 ended session history\n"
        "\u2022 summaries.json \u2014 cached session summaries\n"
        "\u2022 claudewatch.log \u2014 audit log (rotated, max 1 MB)"
    ), y)

    y = _separator(content, y)

    # ── What ClaudeWatch runs ────────────────────────────────────
    y = _heading(content, "What it runs", y)
    y = _body(content, (
        "\u2022 AppleScript \u2014 queries Terminal.app for window list, focuses windows, "
        "closes tabs on session quit, and opens new tabs for resume\n"
        "\u2022 claude -p \u2014 generates one-line session summaries (runs in background, "
        "max 1 at a time)\n"
        "\u2022 terminal-notifier \u2014 sends macOS notifications when sessions need "
        "attention (optional, requires brew install)\n"
        "\u2022 gh / curl \u2014 checks GitHub Releases for updates every 6 hours (public API, no auth)"
    ), y)

    y = _separator(content, y)

    # ── Network access ───────────────────────────────────────────
    y = _heading(content, "Network access", y)
    y = _body(content, (
        "\u2022 One outbound HTTPS call every 6 hours to api.github.com to check "
        "for new releases. No telemetry, no analytics, no data sent."
    ), y)

    y = _separator(content, y)

    # ── Required permissions ─────────────────────────────────────
    y = _heading(content, "Required: Accessibility", y)
    y = _body(content, (
        "Needed to focus terminal windows when you click a session. "
        "Without this, ClaudeWatch can show sessions but cannot switch to them."
    ), y)
    _button(content, "Open Settings", y + 6, _delegate, "openAccessibility_")
    y -= 16

    y = _heading(content, "Required: Automation (Terminal)", y)
    y = _body(content, (
        "Needed to list Terminal.app windows, match them to Claude sessions, "
        "resume sessions in new tabs, and close tabs on quit."
    ), y)
    _button(content, "Open Settings", y + 6, _delegate, "openAutomation_")
    y -= 16

    y = _separator(content, y)

    # ── What it does NOT access ──────────────────────────────────
    y = _heading(content, "What it does NOT access", y)
    y = _body(content, (
        "ClaudeWatch does not access your Photos, Music, Documents, Downloads, "
        "Desktop, Contacts, Calendar, Camera, Microphone, or any files outside "
        "of ~/.claude/. If macOS prompts you for these, you can safely deny them \u2014 "
        "they are triggered by the Python runtime, not by ClaudeWatch."
    ), y)

    # Trim content view to actual height used
    actual_h = content_h - y + 20
    content.setFrame_(NSMakeRect(0, 0, _W, actual_h))
    # Reposition all subviews (shift up so content starts at top)
    offset = actual_h - content_h
    for sub in content.subviews():
        frame = sub.frame()
        sub.setFrame_(NSMakeRect(frame.origin.x, frame.origin.y - offset, frame.size.width, frame.size.height))

    # Scroll view
    scroll_h = _H - 60  # leave room for button at bottom
    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 52, _W, scroll_h))
    scroll.setDocumentView_(content)
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)
    root.addSubview_(scroll)

    # Get Started button at bottom
    btn = NSButton.alloc().initWithFrame_(NSMakeRect((_W - 120) // 2, 12, 120, 32))
    btn.setTitle_("Get Started")
    btn.setBezelStyle_(1)
    btn.setKeyEquivalent_("\r")
    btn.setTarget_(_delegate)
    btn.setAction_(objc.selector(_delegate.dismiss_, signature=b"v@:@"))
    root.addSubview_(btn)

    window.makeKeyAndOrderFront_(None)
    _window = window
