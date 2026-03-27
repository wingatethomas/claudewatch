"""Button factories — interactive controls.

All buttons take a target + action pair for callback wiring.
The `_wire` helper reduces repetition across button types.
"""

from __future__ import annotations

from dataclasses import dataclass

from AppKit import (
    NSButton,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSPopUpButton,
    NSSwitch,
)
from Foundation import NSMakeRect


@dataclass(frozen=True)
class Size:
    """Width x height pair for control sizing."""

    width: float
    height: float


BUTTON_SIZE = Size(100, 24)
TOGGLE_SIZE = Size(46, 22)
ICON_SIZE = Size(18, 18)


def _wire(control: object, target: object, action: object, represented_object: str = "") -> None:
    """Wire target + action + optional representedObject onto a control."""
    control.setTarget_(target)
    control.setAction_(action)
    if represented_object:
        if hasattr(control, "cell"):
            control.cell().setRepresentedObject_(represented_object)
        else:
            control.setRepresentedObject_(represented_object)


def button(
    title: str,
    *,
    target: object,
    action: object,
    size: Size = BUTTON_SIZE,
    font_size: float = 11.0,
) -> NSButton:
    """Standard push button."""
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, size.width, size.height))
    btn.setTitle_(title)
    btn.setBezelStyle_(1)
    btn.setFont_(NSFont.systemFontOfSize_(font_size))
    _wire(btn, target, action)
    return btn


def toggle(*, enabled: bool, target: object, action: object, represented_object: str = "") -> NSSwitch:
    """On/off toggle switch."""
    sw = NSSwitch.alloc().initWithFrame_(NSMakeRect(0, 0, TOGGLE_SIZE.width, TOGGLE_SIZE.height))
    sw.setState_(NSControlStateValueOn if enabled else NSControlStateValueOff)
    _wire(sw, target, action, represented_object)
    return sw


def popup(
    titles: list[str],
    *,
    selected: str | None = None,
    target: object,
    action: object,
    width: float = 160,
) -> NSPopUpButton:
    """Dropdown popup button."""
    p = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, width, 24), False)
    p.setFont_(NSFont.systemFontOfSize_(12.0))
    p.addItemsWithTitles_(titles)
    if selected is not None:
        p.selectItemWithTitle_(selected)
    _wire(p, target, action)
    return p


def link_button(
    title: str,
    *,
    target: object,
    action: object,
    represented_object: str = "",
) -> NSButton:
    """Borderless clickable text (like a hyperlink)."""
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 164, 18))
    btn.setTitle_(title)
    btn.setBordered_(False)
    btn.setFont_(NSFont.systemFontOfSize_(12.0))
    btn.setAlignment_(0)
    _wire(btn, target, action, represented_object)
    return btn


def icon_button(
    *,
    image: object,
    target: object,
    action: object,
    tooltip: str = "",
    size: Size = ICON_SIZE,
) -> NSButton:
    """Borderless icon button."""
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, size.width, size.height))
    btn.setImage_(image)
    btn.setBordered_(False)
    _wire(btn, target, action)
    if tooltip:
        btn.setToolTip_(tooltip)
    return btn
