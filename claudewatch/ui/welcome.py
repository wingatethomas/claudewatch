"""First-launch welcome window — explains permissions and data access."""

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
    NSTextField,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect

from claudewatch.backend.core.settings import get_setting, set_setting
from claudewatch.ui.safety import objc_callback

_W = 500
_H = 520
_PAD = 24
_TEXT_W = _W - _PAD * 2

_window: NSWindow | None = None
_delegate: "_WelcomeDelegate | None" = None


class _WelcomeDelegate(NSObject):
    @objc_callback
    def windowWillClose_(self, notification: object) -> None:  # noqa: N802, ARG002
        global _window, _delegate  # noqa: PLW0603
        _window = None
        _delegate = None

    @objc_callback
    def openAccessibility_(self, sender: object) -> None:  # noqa: N802, ARG002
        subprocess.run(  # noqa: S603, S607
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            check=False,
        )

    @objc_callback
    def openAutomation_(self, sender: object) -> None:  # noqa: N802, ARG002
        subprocess.run(  # noqa: S603, S607
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"],
            check=False,
        )

    @objc_callback
    def dismiss_(self, sender: object) -> None:  # noqa: N802, ARG002
        if _window:
            _window.close()


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
        NSMakeRect(300, 200, _W, _H), style, 2, False
    )
    window.setTitle_("Welcome to ClaudeWatch")
    window.setDelegate_(_delegate)
    window.setReleasedWhenClosed_(False)
    window.center()

    root = window.contentView()
    y = _H - _PAD

    # Title
    y -= 24
    _add_label(root, "Welcome to ClaudeWatch", y, height=24, size=18.0, bold=True)
    y -= 8

    # Subtitle
    y -= 34
    _add_label(
        root,
        "ClaudeWatch monitors your Claude Code sessions from the menu bar.\nGrant these two permissions to get started.",
        y,
        height=34,
        color=NSColor.secondaryLabelColor(),
    )
    y -= 16

    # Accessibility
    _add_separator(root, y)
    y -= 12
    _add_label(root, "Accessibility", y, height=16, bold=True)
    y -= 20
    _add_label(
        root, "Focus terminal windows when you click a session.", y, height=16, color=NSColor.secondaryLabelColor()
    )
    _add_action_button(root, "Open Settings", y, _delegate, "openAccessibility_")
    y -= 24

    # Automation
    _add_separator(root, y)
    y -= 12
    _add_label(root, "Automation (Terminal)", y, height=16, bold=True)
    y -= 20
    _add_label(
        root, "List windows, resume sessions, close tabs on quit.", y, height=16, color=NSColor.secondaryLabelColor()
    )
    _add_action_button(root, "Open Settings", y, _delegate, "openAutomation_")
    y -= 24

    # Privacy
    _add_separator(root, y)
    y -= 12
    _add_label(root, "Privacy", y, height=16, bold=True)
    y -= 20
    _add_label(
        root,
        "ClaudeWatch only reads ~/.claude/ and writes to ~/Library/Application Support/ClaudeWatch/. "
        "It does not access Photos, Music, Documents, Downloads, or any other personal files.",
        y,
        height=48,
        color=NSColor.secondaryLabelColor(),
    )
    y -= 56

    # What it runs
    _add_separator(root, y)
    y -= 12
    _add_label(root, "What it runs", y, height=16, bold=True)
    y -= 20
    _add_label(
        root,
        "AppleScript (Terminal windows)  ·  claude -p (summaries)\nNative notifications  ·  GitHub API (update checks)",
        y,
        height=32,
        color=NSColor.secondaryLabelColor(),
    )
    y -= 44

    # Get Started button
    button = NSButton.alloc().initWithFrame_(NSMakeRect((_W - 140) // 2, max(y, 14), 140, 36))
    button.setTitle_("Get Started")
    button.setBezelStyle_(1)
    button.setKeyEquivalent_("\r")
    button.setFont_(NSFont.systemFontOfSize_(14.0))
    button.setTarget_(_delegate)
    button.setAction_(objc.selector(_delegate.dismiss_, signature=b"v@:@"))
    root.addSubview_(button)

    window.makeKeyAndOrderFront_(None)
    _window = window


# ── Layout helpers ───────────────────────────────────────────────────


def _add_label(  # noqa: PLR0913
    view: object,
    text: str,
    y: float,
    *,
    height: float = 16,
    size: float = 12.0,
    bold: bool = False,
    color: object | None = None,
) -> None:
    text_label = NSTextField.labelWithString_(text)
    text_label.setFrame_(NSMakeRect(_PAD, y, _TEXT_W, height))
    text_label.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if color:
        text_label.setTextColor_(color)
    text_label.setMaximumNumberOfLines_(0)
    view.addSubview_(text_label)


def _add_separator(view: object, y: float) -> None:
    separator = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y, _TEXT_W, 1))
    separator.setBoxType_(2)
    view.addSubview_(separator)


def _add_action_button(view: object, title: str, y: float, delegate: _WelcomeDelegate, action: str) -> None:
    action_button = NSButton.alloc().initWithFrame_(NSMakeRect(_W - _PAD - 120, y - 2, 110, 22))
    action_button.setTitle_(title)
    action_button.setBezelStyle_(1)
    action_button.setControlSize_(1)
    action_button.setFont_(NSFont.systemFontOfSize_(11.0))
    action_button.setTarget_(delegate)
    action_button.setAction_(objc.selector(getattr(delegate, action), signature=b"v@:@"))
    view.addSubview_(action_button)
