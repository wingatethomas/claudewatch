"""Tests for GuideSections composite."""

from AppKit import NSView

from claudewatch.ui.components.composites.guide_sections import build


class TestGuideSections:
    def test_returns_view(self) -> None:
        sections = [("Getting Started", ["Click the menu bar icon", "Sessions grouped by status"])]
        view = build(sections=sections, width=400, height=300)
        assert isinstance(view, NSView)

    def test_multiple_sections(self) -> None:
        sections = [
            ("Getting Started", ["Item 1"]),
            ("Bookmarks", ["Item 2", "Item 3"]),
        ]
        view = build(sections=sections, width=400, height=300)
        assert view is not None

    def test_empty_sections(self) -> None:
        view = build(sections=[], width=400, height=300)
        assert view is not None
