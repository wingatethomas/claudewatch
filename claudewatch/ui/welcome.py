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

_W = 500
_H = 520
_PAD = 24
_TEXT_W = _W - _PAD * 2

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
    y = _H - 40

    # ── Title ────────────────────────────────────────────────────
    _label(root, "Welcome to ClaudeWatch", y, size=18.0, bold=True)
    y -= 24
    _label(
        root,
        "ClaudeWatch monitors your Claude Code sessions from the menu bar.\n"
        "Grant these two permissions to get started.",
        y, height=34, color=NSColor.secondaryLabelColor(),
    )
    y -= 48

    # ── Accessibility ────────────────────────────────────────────
    _sep(root, y + 6)
    y -= 6
    _label(root, "Accessibility", y, bold=True)
    y -= 18
    _label(root, "Focus terminal windows when you click a session.", y, color=NSColor.secondaryLabelColor())
    _action_btn(root, "Open Settings", y, _delegate, "openAccessibility_")
    y -= 32

    # ── Automation ───────────────────────────────────────────────
    _sep(root, y + 6)
    y -= 6
    _label(root, "Automation (Terminal)", y, bold=True)
    y -= 18
    _label(root, "List windows, resume sessions, close tabs on quit.", y, color=NSColor.secondaryLabelColor())
    _action_btn(root, "Open Settings", y, _delegate, "openAutomation_")
    y -= 32

    # ── Privacy ──────────────────────────────────────────────────
    _sep(root, y + 6)
    y -= 6
    _label(root, "Privacy", y, bold=True)
    y -= 18
    _label(
        root,
        "ClaudeWatch only reads ~/.claude/ and writes to\n"
        "~/Library/Application Support/ClaudeWatch/.\n\n"
        "It does not access Photos, Music, Documents, Downloads,\n"
        "or any other personal files. Deny those prompts if they appear.",
        y, height=64, color=NSColor.secondaryLabelColor(),
    )
    y -= 78

    # ── What it runs ─────────────────────────────────────────────
    _sep(root, y + 6)
    y -= 6
    _label(root, "What it runs", y, bold=True)
    y -= 18
    _label(
        root,
        "AppleScript (Terminal windows)  ·  claude -p (summaries)\n"
        "Native notifications  ·  GitHub API (update checks)",
        y, height=32, color=NSColor.secondaryLabelColor(),
    )
    y -= 50

    # ── Get Started ──────────────────────────────────────────────
    btn = NSButton.alloc().initWithFrame_(NSMakeRect((_W - 140) // 2, max(y, 14), 140, 36))
    btn.setTitle_("Get Started")
    btn.setBezelStyle_(1)
    btn.setKeyEquivalent_("\r")
    btn.setFont_(NSFont.systemFontOfSize_(14.0))
    btn.setTarget_(_delegate)
    btn.setAction_(objc.selector(_delegate.dismiss_, signature=b"v@:@"))
    root.addSubview_(btn)

    window.makeKeyAndOrderFront_(None)
    _window = window


# ── Layout helpers ───────────────────────────────────────────────────


def _label(  # noqa: PLR0913
    view: object,
    text: str,
    y: int,
    *,
    height: int = 16,
    size: float = 12.0,
    bold: bool = False,
    color: object | None = None,
) -> None:
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(_PAD, y, _TEXT_W, height))
    label.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if color:
        label.setTextColor_(color)
    label.setMaximumNumberOfLines_(0)
    view.addSubview_(label)


def _sep(view: object, y: int) -> None:
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y, _TEXT_W, 1))
    sep.setBoxType_(2)
    view.addSubview_(sep)


def _action_btn(view: object, title: str, y: int, delegate: _WelcomeDelegate, action: str) -> None:
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(_W - _PAD - 120, y - 2, 110, 22))
    btn.setTitle_(title)
    btn.setBezelStyle_(1)
    btn.setControlSize_(1)
    btn.setFont_(NSFont.systemFontOfSize_(11.0))
    btn.setTarget_(delegate)
    btn.setAction_(objc.selector(getattr(delegate, action), signature=b"v@:@"))
    view.addSubview_(btn)
