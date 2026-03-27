"""Tests for ChangelogView composite."""

from AppKit import NSView

from claudewatch.ui.components.composites.changelog import build_changelog


class TestChangelogView:
    def test_returns_view(self) -> None:
        releases = [("v0.7.5", ["Launch at login", "Homebrew updates"])]
        view = build_changelog(releases=releases, width=400, height=300)
        assert isinstance(view, NSView)

    def test_multiple_releases(self) -> None:
        releases = [
            ("v0.7.5", ["Feature A"]),
            ("v0.7.4", ["Feature B", "Feature C"]),
        ]
        view = build_changelog(releases=releases, width=400, height=300)
        assert view is not None

    def test_empty_releases(self) -> None:
        view = build_changelog(releases=[], width=400, height=300)
        assert view is not None
