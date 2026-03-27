"""Tests for FeatureCard composite."""

from AppKit import NSSwitch, NSView

from claudewatch.ui.components.composites.feature_card import FacetSpec, build


def _find_all(view: NSView, cls: type) -> list:
    """Recursively find all instances of cls in view hierarchy."""
    found = []
    for sub in view.subviews():
        if isinstance(sub, cls):
            found.append(sub)
        found.extend(_find_all(sub, cls))
    return found


class TestFeatureCard:
    def test_returns_view(self) -> None:
        view = build(title="Notifications", description="Get alerts", enabled=True, on_toggle=lambda _: None)
        assert isinstance(view, NSView)

    def test_contains_toggle(self) -> None:
        view = build(title="Notifications", description="Get alerts", enabled=True, on_toggle=lambda _: None)
        switches = _find_all(view, NSSwitch)
        assert len(switches) == 1

    def test_toggle_reflects_enabled(self) -> None:
        view = build(title="Test", description="", enabled=False, on_toggle=lambda _: None)
        switches = _find_all(view, NSSwitch)
        assert switches[0].state() == 0  # NSControlStateValueOff

    def test_no_description_still_works(self) -> None:
        view = build(title="Minimal", description="", enabled=True, on_toggle=lambda _: None)
        assert view is not None

    def test_with_facets(self) -> None:
        facets = [FacetSpec(label="Sound", value="Glass", choices=("Glass", "Ping", "Pop"))]
        view = build(
            title="Notifications",
            description="Get alerts",
            enabled=True,
            on_toggle=lambda _: None,
            facets=facets,
            on_facet_change=lambda _k, _v: None,
        )
        assert view is not None
