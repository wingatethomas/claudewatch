"""Feature toggle and facet change handlers."""

from __future__ import annotations

from AppKit import NSControlStateValueOn, NSSound

from claudewatch.backend.core import features
from claudewatch.backend.core.login_item import sync_login_item
from claudewatch.ui.safety import get_represented_object


def handle_toggle(delegate: object, sender: object) -> None:
    """Handle feature toggle switch."""
    key = get_represented_object(sender)
    enabled = sender.state() == NSControlStateValueOn
    features.set_enabled(key, enabled)
    for ctrl in delegate._feature_controls.get(key, []):
        ctrl.setEnabled_(enabled)
    if key == "launch_at_login":
        sync_login_item(enabled)


def handle_facet_change(delegate: object, sender: object) -> None:
    """Handle facet dropdown or control change."""
    info = get_represented_object(sender)
    key, facet_name = info.split("|", 1)
    if hasattr(sender, "titleOfSelectedItem"):
        value: object = sender.titleOfSelectedItem()
    else:
        value = sender.state() == NSControlStateValueOn
    features.set_facet(key, facet_name, value)
    if key == "notifications" and facet_name == "sound":
        sound = NSSound.soundNamed_(value)
        if sound:
            sound.play()


def handle_facet_bool_change(delegate: object, sender: object) -> None:  # noqa: ARG001
    """Handle boolean facet toggle."""
    info = get_represented_object(sender)
    key, facet_name = info.split("|", 1)
    value = sender.state() == NSControlStateValueOn
    features.set_facet(key, facet_name, value)
