"""Native macOS preferences window using PyObjC."""

import os
import subprocess
import webbrowser

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBox,
    NSButton,
    NSButtonTypeSwitch,
    NSColor,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSPopUpButton,
    NSSound,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSObject

from claudewatch import __version__
from claudewatch.backend.repositories.config import get_available_sounds, get_setting, set_setting

_REPO_URL = "https://github.com/wingatethomas/claudewatch"
_W = 320
_H = 210
_PAD = 24
_INNER = _W - _PAD * 2

_window: NSWindow | None = None
_delegate: "_PrefsDelegate | None" = None


class _PrefsDelegate(NSObject):
    """Handles preferences window control actions."""

    def notificationsToggled_(self, sender: objc.objc_object) -> None:
        set_setting("notifications_enabled", sender.state() == NSControlStateValueOn)

    def soundChanged_(self, sender: objc.objc_object) -> None:
        sound_name = sender.titleOfSelectedItem()
        set_setting("notification_sound", sound_name)
        sound = NSSound.soundNamed_(sound_name)
        if sound:
            sound.play()

    def viewAuditLog_(self, sender: objc.objc_object) -> None:
        log_path = os.path.expanduser("~/.claude/claudewatch.log")
        if os.path.exists(log_path):
            subprocess.run(["open", "-a", "Console", log_path], check=False)  # noqa: S603, S607

    def openRepo_(self, sender: objc.objc_object) -> None:
        webbrowser.open(_REPO_URL)

    def windowWillClose_(self, notification: objc.objc_object) -> None:
        global _window  # noqa: PLW0603
        _window = None


def _make_section_box(x: float, y: float, w: float, h: float) -> NSBox:
    """Create a rounded, grouped section box (like macOS Settings cards)."""
    box = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    box.setBoxType_(4)  # NSBoxCustom
    box.setBorderType_(1)  # NSLineBorder
    box.setCornerRadius_(8.0)
    box.setFillColor_(NSColor.controlBackgroundColor())
    box.setBorderColor_(NSColor.separatorColor())
    box.setTitlePosition_(0)  # NSNoTitle
    return box


def _build_ui(content: objc.objc_object, delegate: _PrefsDelegate) -> None:  # noqa: PLR0915
    """Build all UI controls."""
    y = _H - 20

    # ── Branding ──────────────────────────────────
    # App name prominent, version subtle beside it
    name = NSTextField.labelWithString_("✦ ClaudeWatch")
    name.setFrame_(NSMakeRect(_PAD, y - 22, 160, 22))
    name.setFont_(NSFont.boldSystemFontOfSize_(15.0))
    content.addSubview_(name)

    ver = NSTextField.labelWithString_(f"v{__version__}")
    ver.setFrame_(NSMakeRect(_PAD + 162, y - 19, 60, 16))
    ver.setFont_(NSFont.systemFontOfSize_(11.0))
    ver.setTextColor_(NSColor.tertiaryLabelColor())
    content.addSubview_(ver)

    y -= 38

    # ── Notifications section ─────────────────────
    section_h = 68
    section = _make_section_box(_PAD, y - section_h, _INNER, section_h)
    content.addSubview_(section)

    section_content = section.contentView()
    inner_w = _INNER - 24  # padding inside box
    sy = section_h - 16

    # Toggle
    checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(12, sy - 20, inner_w, 20))
    checkbox.setButtonType_(NSButtonTypeSwitch)
    checkbox.setTitle_("Enable notifications")
    checkbox.setFont_(NSFont.systemFontOfSize_(13.0))
    checkbox.setState_(NSControlStateValueOn if get_setting("notifications_enabled") else NSControlStateValueOff)
    checkbox.setTarget_(delegate)
    checkbox.setAction_(objc.selector(delegate.notificationsToggled_, signature=b"v@:@"))
    section_content.addSubview_(checkbox)

    sy -= 32

    # Sound row
    sound_label = NSTextField.labelWithString_("Alert sound")
    sound_label.setFrame_(NSMakeRect(12, sy - 20, 80, 20))
    sound_label.setFont_(NSFont.systemFontOfSize_(13.0))
    sound_label.setTextColor_(NSColor.secondaryLabelColor())
    section_content.addSubview_(sound_label)

    sound_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(100, sy - 22, inner_w - 100, 24), False,
    )
    sound_popup.setFont_(NSFont.systemFontOfSize_(12.0))
    sound_popup.addItemsWithTitles_(list(get_available_sounds()))
    sound_popup.selectItemWithTitle_(str(get_setting("notification_sound")))
    sound_popup.setTarget_(delegate)
    sound_popup.setAction_(objc.selector(delegate.soundChanged_, signature=b"v@:@"))
    section_content.addSubview_(sound_popup)

    y -= section_h + 12

    # ── Footer ────────────────────────────────────
    # Centered row of subtle link buttons
    footer = NSView.alloc().initWithFrame_(NSMakeRect(_PAD, y - 20, _INNER, 20))
    content.addSubview_(footer)

    log_link = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 70, 20))
    log_link.setTitle_("Audit Log")
    log_link.setBezelStyle_(0)
    log_link.setBordered_(False)
    log_link.setFont_(NSFont.systemFontOfSize_(11.0))
    log_link.setContentTintColor_(NSColor.tertiaryLabelColor())
    log_link.setTarget_(delegate)
    log_link.setAction_(objc.selector(delegate.viewAuditLog_, signature=b"v@:@"))
    footer.addSubview_(log_link)

    dot = NSTextField.labelWithString_("·")
    dot.setFrame_(NSMakeRect(70, 0, 10, 20))
    dot.setFont_(NSFont.systemFontOfSize_(11.0))
    dot.setTextColor_(NSColor.quaternaryLabelColor())
    footer.addSubview_(dot)

    repo_link = NSButton.alloc().initWithFrame_(NSMakeRect(80, 0, 55, 20))
    repo_link.setTitle_("GitHub")
    repo_link.setBezelStyle_(0)
    repo_link.setBordered_(False)
    repo_link.setFont_(NSFont.systemFontOfSize_(11.0))
    repo_link.setContentTintColor_(NSColor.tertiaryLabelColor())
    repo_link.setTarget_(delegate)
    repo_link.setAction_(objc.selector(delegate.openRepo_, signature=b"v@:@"))
    footer.addSubview_(repo_link)

    # Center the footer links
    total_link_w = 135
    footer_x = (_INNER - total_link_w) / 2
    footer.setFrame_(NSMakeRect(_PAD + footer_x, y - 20, total_link_w, 20))


def show_preferences() -> None:
    """Show (or bring to front) the preferences window."""
    global _window, _delegate  # noqa: PLW0603

    if _window is not None:
        _window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        return

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    _delegate = _PrefsDelegate.alloc().init()

    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(200, 200, _W, _H),
        style,
        2,  # NSBackingStoreBuffered
        False,
    )
    window.setTitle_("Preferences")
    window.setDelegate_(_delegate)
    window.setReleasedWhenClosed_(False)
    # Normal window level — floating (3) steals focus from rumps dialogs

    _build_ui(window.contentView(), _delegate)

    _window = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
