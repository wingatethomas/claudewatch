"""Tests for DangerZone composite."""

from AppKit import NSButton, NSView

from claudewatch.ui.components.composites.danger_zone import DangerAction, build_danger_zone


class TestDangerZone:
    def test_returns_view(self) -> None:
        actions = [DangerAction(label="Clear bookmarks", button_text="Clear...", on_click=lambda: None)]
        view = build_danger_zone(actions=actions)
        assert isinstance(view, NSView)

    def test_renders_buttons_for_each_action(self) -> None:
        actions = [
            DangerAction(label="Clear bookmarks", button_text="Clear...", on_click=lambda: None),
            DangerAction(label="Clear summaries", button_text="Clear...", on_click=lambda: None),
        ]
        view = build_danger_zone(actions=actions)
        buttons = _find_all_buttons(view)
        assert len(buttons) >= 2

    def test_empty_actions(self) -> None:
        view = build_danger_zone(actions=[])
        assert view is not None


def _find_all_buttons(view: NSView) -> list[NSButton]:
    """Recursively find all NSButton instances in a view hierarchy."""
    buttons = []
    for sub in view.subviews():
        if isinstance(sub, NSButton):
            buttons.append(sub)
        buttons.extend(_find_all_buttons(sub))
    return buttons
