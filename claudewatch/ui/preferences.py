"""System Settings-style preferences window using PyObjC."""

import os
import re
import subprocess
import webbrowser

import objc
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBox,
    NSButton,
    NSButtonTypeSwitch,
    NSColor,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSMenu,
    NSMenuItem,
    NSMutableAttributedString,
    NSPopUpButton,
    NSSound,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from AppKit import NSScrollView as AppKitScrollView
from Foundation import NSMakeRect, NSMakeSize, NSObject, NSRange

from claudewatch import __version__
from claudewatch.backend.helpers import escape_applescript, run_applescript
from claudewatch.backend.repositories.bookmarks import get_pinned_cwds
from claudewatch.backend.repositories.config import get_available_sounds, get_setting, set_setting
from claudewatch.backend.repositories.history import get_history, remove_history_entry
from claudewatch.backend.services.usage import MODEL_DISPLAY_NAMES
from claudewatch.ui.activity import show_activity

_REPO_URL = "https://github.com/wingatethomas/claudewatch"

_W = 500
_H = 420
_PAD = 20
_CARD_PAD = 16
_CARD_GAP = 12
_CARD_RADIUS = 10.0
_CONTENT_W = _W - _PAD * 2
_ROW_H = 32

_window: NSWindow | None = None
_delegate: "_PrefsDelegate | None" = None


class _FlippedView(NSView):
    """NSView subclass with flipped coordinates (y=0 at top)."""

    def isFlipped(self) -> bool:  # noqa: N802
        return True


# ── Delegate ──────────────────────────────────────────────────────────


class _PrefsDelegate(NSObject):
    """Handles preferences window actions."""

    def notificationsToggled_(self, sender: objc.objc_object) -> None:
        set_setting("notifications_enabled", sender.state() == NSControlStateValueOn)

    def soundChanged_(self, sender: objc.objc_object) -> None:
        sound_name = sender.titleOfSelectedItem()
        set_setting("notification_sound", sound_name)
        sound = NSSound.soundNamed_(sound_name)
        if sound:
            sound.play()

    def expiryChanged_(self, sender: objc.objc_object) -> None:
        title = sender.titleOfSelectedItem()
        days = 0 if title == "Never" else int(title.rstrip(" days"))
        set_setting("pin_expiry_days", days)

    def viewAuditLog_(self, sender: objc.objc_object) -> None:
        log_path = os.path.expanduser("~/.claude/claudewatch.log")
        if os.path.exists(log_path):
            subprocess.run(["open", "-a", "Console", log_path], check=False)  # noqa: S603, S607

    def openRepo_(self, sender: objc.objc_object) -> None:
        webbrowser.open(_REPO_URL)

    def deleteHistoryEntry_(self, sender: objc.objc_object) -> None:
        cwd = str(sender.representedObject())
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Delete this session from history?")
        alert.setInformativeText_("This cannot be undone.")
        alert.addButtonWithTitle_("Delete")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() == NSAlertFirstButtonReturn:
            remove_history_entry(cwd)

    def resumeSession_(self, sender: objc.objc_object) -> None:
        data = str(sender.representedObject())
        if "|" not in data:
            return
        sid, cwd = data.split("|", 1)
        if not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", sid):
            return
        safe_cwd = escape_applescript(cwd) if cwd else ""
        cd_cmd = f'cd \\"{safe_cwd}\\" && ' if safe_cwd else ""
        run_applescript(f'''
            tell application "Terminal"
                activate
                do script "{cd_cmd}claude -r {sid}"
            end tell
        ''')

    def viewActivity_(self, sender: objc.objc_object) -> None:
        data = str(sender.representedObject())
        if "|" not in data:
            return
        project, cwd = data.split("|", 1)
        show_activity(project, cwd)

    def windowWillClose_(self, notification: objc.objc_object) -> None:
        global _window  # noqa: PLW0603
        _window = None


# ── Card helpers ──────────────────────────────────────────────────────


def _make_card(parent: NSView, y: float, height: float) -> NSBox:
    """Create a rounded card and add it to parent. Returns the card."""
    card = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y, _CONTENT_W, height))
    card.setBoxType_(4)  # NSBoxCustom
    card.setCornerRadius_(_CARD_RADIUS)
    card.setBorderWidth_(0)
    card.setFillColor_(NSColor.controlBackgroundColor())
    card.setContentViewMargins_(NSMakeSize(0, 0))
    parent.addSubview_(card)
    return card


def _make_section_header(parent: NSView, text: str, y: float) -> None:
    """Add an uppercase section header label."""
    label = NSTextField.labelWithString_(text.upper())
    label.setFrame_(NSMakeRect(_PAD + 4, y, 200, 14))
    label.setFont_(NSFont.systemFontOfSize_weight_(11.0, 0.6))
    label.setTextColor_(NSColor.secondaryLabelColor())
    parent.addSubview_(label)


def _make_row_label(text: str, x: float, y: float, w: float) -> NSTextField:
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(x, y, w, 18))
    label.setFont_(NSFont.systemFontOfSize_(13.0))
    return label


def _make_hint(text: str, x: float, y: float, w: float) -> NSTextField:
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(x, y, w, 14))
    label.setFont_(NSFont.systemFontOfSize_(11.0))
    label.setTextColor_(NSColor.tertiaryLabelColor())
    return label


def _make_separator(x: float, y: float, w: float) -> NSBox:
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, 1))
    sep.setBoxType_(2)
    return sep


def _make_link_button(
    text: str,
    x: float,
    y: float,
    target: object,
    action: objc.selector,
) -> NSButton:
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, len(text) * 7 + 16, 18))
    btn.setBezelStyle_(0)
    btn.setBordered_(False)
    attr = NSMutableAttributedString.alloc().initWithString_(text)
    r = NSRange(0, len(text))
    attr.addAttribute_value_range_("NSFont", NSFont.systemFontOfSize_(11.0), r)
    attr.addAttribute_value_range_("NSColor", NSColor.systemBlueColor(), r)
    btn.setAttributedTitle_(attr)
    btn.setTarget_(target)
    btn.setAction_(action)
    return btn


# ── Public API ────────────────────────────────────────────────────────


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
        2,
        False,
    )
    window.setTitle_("ClaudeWatch")
    window.setDelegate_(_delegate)
    window.setReleasedWhenClosed_(False)

    # Scrollable content area
    scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, _H))
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)

    # Calculate total content height
    _total_h = 20 + (80 + 20) + _CARD_GAP + (60 + 20) + _CARD_GAP + (220 + 20) + _CARD_GAP + (100 + 20) + 20
    content = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, _W, max(_total_h, _H)))

    # Build cards top-down (flipped view: y increases downward)
    y = 10
    _make_section_header(content, "Notifications", y)
    y += 18
    notifications_card = _make_card(content, y, 80)
    _build_notifications_content(notifications_card.contentView(), _delegate)
    y += 80 + _CARD_GAP

    _make_section_header(content, "Sessions", y)
    y += 18
    sessions_card = _make_card(content, y, 60)
    _build_sessions_content(sessions_card.contentView(), _delegate)
    y += 60 + _CARD_GAP

    _make_section_header(content, "Recent Sessions", y)
    y += 18
    history_card = _make_card(content, y, 220)
    _build_history_content(history_card.contentView(), _delegate)
    y += 220 + _CARD_GAP

    _make_section_header(content, "About", y)
    y += 18
    about_card = _make_card(content, y, 100)
    _build_about_content(about_card.contentView(), _delegate)

    scroll.setDocumentView_(content)
    window.setContentView_(scroll)

    _window = window
    window.center()
    window.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


# ── Card content builders (operate on card.contentView()) ─────────────


def _build_notifications_content(cv: NSView, delegate: _PrefsDelegate) -> None:
    inner_w = _CONTENT_W - _CARD_PAD * 2
    ry = 12

    toggle = NSButton.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, ry, inner_w, 20))
    toggle.setButtonType_(NSButtonTypeSwitch)
    toggle.setTitle_("Enable notifications")
    toggle.setFont_(NSFont.systemFontOfSize_(13.0))
    toggle.setState_(NSControlStateValueOn if get_setting("notifications_enabled") else NSControlStateValueOff)
    toggle.setTarget_(delegate)
    toggle.setAction_(objc.selector(delegate.notificationsToggled_, signature=b"v@:@"))
    cv.addSubview_(toggle)

    ry += _ROW_H
    cv.addSubview_(_make_separator(_CARD_PAD, ry, inner_w))
    ry += 8

    cv.addSubview_(_make_row_label("Alert sound", _CARD_PAD, ry, 80))
    sound_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(_CARD_PAD + 90, ry - 2, inner_w - 90, 22),
        False,
    )
    sound_popup.setFont_(NSFont.systemFontOfSize_(12.0))
    sound_popup.setToolTip_("System sounds from /System/Library/Sounds/")
    sound_popup.addItemsWithTitles_(list(get_available_sounds()))
    sound_popup.selectItemWithTitle_(str(get_setting("notification_sound")))
    sound_popup.setTarget_(delegate)
    sound_popup.setAction_(objc.selector(delegate.soundChanged_, signature=b"v@:@"))
    cv.addSubview_(sound_popup)


def _build_sessions_content(cv: NSView, delegate: _PrefsDelegate) -> None:
    inner_w = _CONTENT_W - _CARD_PAD * 2
    ry = 10

    cv.addSubview_(_make_row_label("Pin expiry", _CARD_PAD, ry + 2, 80))
    expiry_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(_CARD_PAD + 90, ry, inner_w - 90, 22),
        False,
    )
    expiry_popup.setFont_(NSFont.systemFontOfSize_(12.0))
    options = ["Never", "7 days", "14 days", "30 days", "60 days", "90 days"]
    expiry_popup.addItemsWithTitles_(options)
    current = int(get_setting("pin_expiry_days") or 30)
    if current <= 0:
        expiry_popup.selectItemWithTitle_("Never")
    else:
        expiry_popup.selectItemWithTitle_(f"{current} days")
    expiry_popup.setTarget_(delegate)
    expiry_popup.setAction_(objc.selector(delegate.expiryChanged_, signature=b"v@:@"))
    cv.addSubview_(expiry_popup)

    ry += 26
    cv.addSubview_(_make_hint("Pinned sessions expire after this period of inactivity.", _CARD_PAD, ry, inner_w))


def _build_history_content(cv: NSView, delegate: _PrefsDelegate) -> None:  # noqa: PLR0915
    inner_w = _CONTENT_W - _CARD_PAD * 2
    card_h = 220
    history = get_history()

    if not history:
        cv.addSubview_(_make_hint("No session history yet.", _CARD_PAD, card_h // 2, inner_w))
        return

    scroll = AppKitScrollView.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, 0, inner_w, card_h))
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)

    _entry_h = 44
    entry_w = inner_w - 16
    list_h = max(len(history) * _entry_h, card_h)
    list_view = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, entry_w, list_h))

    pinned_cwds = get_pinned_cwds()
    ey = 4

    for entry in history:
        proj = entry.get("project", "unknown")
        raw_model = entry.get("model", "")
        model = MODEL_DISPLAY_NAMES.get(raw_model, raw_model)
        ended = entry.get("ended_at", "")[:16].replace("T", " ")
        sid = entry.get("session_id", "")
        cwd = entry.get("cwd", "")
        pin_mark = " ★" if cwd in pinned_cwds else ""

        row = NSView.alloc().initWithFrame_(NSMakeRect(0, ey, entry_w, _entry_h - 4))

        name_label = NSTextField.labelWithString_(f"{proj}{pin_mark}")
        name_label.setFrame_(NSMakeRect(0, 2, entry_w - 140, 18))
        name_label.setFont_(NSFont.systemFontOfSize_(13.0))
        row.addSubview_(name_label)

        meta_text = ended
        if model:
            meta_text += f"  ·  {model}"
        meta_label = NSTextField.labelWithString_(meta_text)
        meta_label.setFrame_(NSMakeRect(0, 20, entry_w - 140, 14))
        meta_label.setFont_(NSFont.systemFontOfSize_(10.0))
        meta_label.setTextColor_(NSColor.tertiaryLabelColor())
        row.addSubview_(meta_label)

        bx = entry_w - 60
        resume_link = _make_link_button(
            "Resume",
            bx,
            6,
            delegate,
            objc.selector(delegate.resumeSession_, signature=b"v@:@"),
        )
        resume_link.setRepresentedObject_(f"{sid}|{cwd}")
        row.addSubview_(resume_link)

        bx -= 56
        activity_link = _make_link_button(
            "Activity",
            bx,
            6,
            delegate,
            objc.selector(delegate.viewActivity_, signature=b"v@:@"),
        )
        activity_link.setRepresentedObject_(f"{proj}|{cwd}")
        row.addSubview_(activity_link)

        # Right-click context menu
        menu = NSMenu.alloc().init()
        resume_mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Resume", "resumeSession:", "")
        resume_mi.setTarget_(delegate)
        resume_mi.setRepresentedObject_(f"{sid}|{cwd}")
        menu.addItem_(resume_mi)

        activity_mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Activity", "viewActivity:", "")
        activity_mi.setTarget_(delegate)
        activity_mi.setRepresentedObject_(f"{proj}|{cwd}")
        menu.addItem_(activity_mi)

        menu.addItem_(NSMenuItem.separatorItem())

        delete_mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Delete", "deleteHistoryEntry:", "")
        delete_mi.setTarget_(delegate)
        delete_mi.setRepresentedObject_(cwd)
        delete_attr = NSMutableAttributedString.alloc().initWithString_("Delete")
        delete_attr.addAttribute_value_range_("NSColor", NSColor.systemRedColor(), NSRange(0, 6))
        delete_mi.setAttributedTitle_(delete_attr)
        menu.addItem_(delete_mi)

        row.setMenu_(menu)
        list_view.addSubview_(row)

        ey += _entry_h
        if ey < list_h:
            list_view.addSubview_(_make_separator(0, ey - 4, entry_w))

    scroll.setDocumentView_(list_view)
    cv.addSubview_(scroll)


def _build_about_content(cv: NSView, delegate: _PrefsDelegate) -> None:
    inner_w = _CONTENT_W - _CARD_PAD * 2
    ry = 10

    cv.addSubview_(_make_row_label("Version", _CARD_PAD, ry, 100))
    ver = NSTextField.labelWithString_(f"v{__version__}")
    ver.setFrame_(NSMakeRect(inner_w - 60, ry, 76, 18))
    ver.setFont_(NSFont.systemFontOfSize_(13.0))
    ver.setTextColor_(NSColor.secondaryLabelColor())
    ver.setAlignment_(2)  # NSTextAlignmentRight
    cv.addSubview_(ver)

    ry += 24
    cv.addSubview_(_make_separator(_CARD_PAD, ry, inner_w))
    ry += 8

    cv.addSubview_(_make_row_label("Audit Log", _CARD_PAD, ry, 100))
    log_link = _make_link_button(
        "Open in Console ›",
        inner_w - 100,
        ry,
        delegate,
        objc.selector(delegate.viewAuditLog_, signature=b"v@:@"),
    )
    cv.addSubview_(log_link)

    ry += 24
    cv.addSubview_(_make_separator(_CARD_PAD, ry, inner_w))
    ry += 8

    cv.addSubview_(_make_row_label("Source Code", _CARD_PAD, ry, 100))
    repo_link = _make_link_button(
        "GitHub ›",
        inner_w - 40,
        ry,
        delegate,
        objc.selector(delegate.openRepo_, signature=b"v@:@"),
    )
    cv.addSubview_(repo_link)
