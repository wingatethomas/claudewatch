"""Tests for theme — color scheme lookup and status color mapping."""

from unittest.mock import patch

from claudewatch.backend.core.models import SessionStatus
from claudewatch.ui.components.tokens import STATUS_SCHEMES, get_scheme


class TestGetScheme:
    def test_exact_match(self) -> None:
        scheme = get_scheme("Default")
        assert scheme.name == "Default"

    def test_case_insensitive(self) -> None:
        scheme = get_scheme("default")
        assert scheme.name == "Default"

    def test_case_insensitive_blue_orange(self) -> None:
        scheme = get_scheme("blue-orange")
        assert scheme.name == "Blue-Orange"

    def test_case_insensitive_high_contrast(self) -> None:
        scheme = get_scheme("high contrast")
        assert scheme.name == "High Contrast"

    def test_unknown_returns_default(self) -> None:
        scheme = get_scheme("nonexistent")
        assert scheme.name == "Default"

    def test_empty_returns_default(self) -> None:
        scheme = get_scheme("")
        assert scheme.name == "Default"

    def test_all_schemes_have_three_colors(self) -> None:
        for key, scheme in STATUS_SCHEMES.items():
            assert scheme.attention is not None, f"{key} missing attention"
            assert scheme.working is not None, f"{key} missing working"
            assert scheme.idle is not None, f"{key} missing idle"


class TestThemeStatusColors:
    def test_default_scheme_returns_colors(self) -> None:
        from claudewatch.ui.theme import theme

        color = theme.status_color(SessionStatus.ATTENTION)
        assert color is not None

    def test_all_statuses_have_colors(self) -> None:
        from claudewatch.ui.theme import get_status_colors

        colors = get_status_colors()
        assert SessionStatus.ATTENTION in colors
        assert SessionStatus.WORKING in colors
        assert SessionStatus.IDLE in colors

    @patch("claudewatch.ui.theme.features.get_facet", return_value="High Contrast")
    def test_scheme_change_affects_colors(self, _mock: object) -> None:
        from claudewatch.ui.theme import theme

        scheme = theme.scheme
        assert scheme.name == "High Contrast"

    @patch("claudewatch.ui.theme.features.get_facet", return_value="nonexistent")
    def test_invalid_scheme_falls_back(self, _mock: object) -> None:
        from claudewatch.ui.theme import theme

        scheme = theme.scheme
        assert scheme.name == "Default"

    @patch("claudewatch.ui.theme.features.get_facet", return_value=None)
    def test_none_facet_uses_default(self, _mock: object) -> None:
        from claudewatch.ui.theme import theme

        scheme = theme.scheme
        assert scheme.name == "Default"
