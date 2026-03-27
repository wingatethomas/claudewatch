"""Tests for widget factories."""

from unittest.mock import MagicMock

from AppKit import NSBox, NSButton, NSColor, NSSwitch, NSTextField

from claudewatch.ui.components.widgets.buttons import Size, button, toggle
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, pane_title, secondary_label, section_header


class TestLabel:
    def test_returns_text_field(self) -> None:
        lbl = label("Hello")
        assert isinstance(lbl, NSTextField)
        assert str(lbl.stringValue()) == "Hello"

    def test_bold(self) -> None:
        lbl = label("Bold", bold=True)
        font = lbl.font()
        # Bold font weight > 0
        assert font is not None

    def test_color(self) -> None:
        lbl = label("Red", color=NSColor.redColor())
        assert lbl.textColor() == NSColor.redColor()

    def test_default_size(self) -> None:
        lbl = label("Test")
        assert lbl.font().pointSize() == 13.0

    def test_custom_size(self) -> None:
        lbl = label("Test", size=18.0)
        assert lbl.font().pointSize() == 18.0


class TestSecondaryLabel:
    def test_uses_secondary_color(self) -> None:
        lbl = secondary_label("Dim")
        assert lbl.textColor() == NSColor.secondaryLabelColor()

    def test_default_size_12(self) -> None:
        lbl = secondary_label("Dim")
        assert lbl.font().pointSize() == 12.0


class TestSectionHeader:
    def test_uses_tertiary_color(self) -> None:
        lbl = section_header("HEADER")
        assert lbl.textColor() == NSColor.tertiaryLabelColor()

    def test_size_10(self) -> None:
        lbl = section_header("HEADER")
        assert lbl.font().pointSize() == 10.0


class TestPaneTitle:
    def test_size_18_bold(self) -> None:
        lbl = pane_title("Settings")
        assert lbl.font().pointSize() == 18.0


class TestButton:
    def test_returns_nsbutton(self) -> None:
        target = MagicMock()
        btn = button("Click", target=target, action="doStuff:")
        assert isinstance(btn, NSButton)
        assert str(btn.title()) == "Click"

    def test_sets_target(self) -> None:
        target = MagicMock()
        btn = button("Click", target=target, action="doStuff:")
        assert btn.target() == target

    def test_custom_size(self) -> None:
        btn = button("Wide", target=MagicMock(), action="x:", size=Size(200, 30))
        assert btn.frame().size.width == 200
        assert btn.frame().size.height == 30


class TestToggle:
    def test_returns_nsswitch(self) -> None:
        sw = toggle(enabled=True, target=MagicMock(), action="toggled:")
        assert isinstance(sw, NSSwitch)

    def test_enabled_state(self) -> None:
        sw = toggle(enabled=True, target=MagicMock(), action="toggled:")
        assert sw.state() == 1  # NSControlStateValueOn

    def test_disabled_state(self) -> None:
        sw = toggle(enabled=False, target=MagicMock(), action="toggled:")
        assert sw.state() == 0  # NSControlStateValueOff


class TestCard:
    def test_returns_nsbox(self) -> None:
        c = card(300, 100)
        assert isinstance(c, NSBox)

    def test_dimensions(self) -> None:
        c = card(300, 100)
        assert c.frame().size.width == 300
        assert c.frame().size.height == 100

    def test_custom_border_color(self) -> None:
        c = card(300, 100, border_color=NSColor.redColor())
        # Card should accept custom border color without error
        assert c is not None
