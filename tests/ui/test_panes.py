"""Integration tests for preference panes — ensures they render without crashing.

These tests catch DTO interface changes and missing imports that unit tests miss.
"""

from unittest.mock import MagicMock, patch

from AppKit import NSView


def _make_delegate() -> MagicMock:
    """Create a mock delegate with required attributes."""
    delegate = MagicMock(spec=[])  # empty spec — don't auto-generate attributes
    delegate._feature_controls = {}
    delegate._history_search = ""
    delegate._history_sort = "date"
    delegate._history_sort_asc = False
    delegate._history_bookmarked_only = False
    delegate._history_scroll = None
    delegate._history_inner = None
    # ObjC selector methods need to exist as real callables
    delegate.featureToggled_ = lambda self, sender: None
    delegate.facetChanged_ = lambda self, sender: None
    delegate.facetBoolChanged_ = lambda self, sender: None
    delegate.clearBookmarks_ = lambda self, sender: None
    delegate.clearSummaries_ = lambda self, sender: None
    delegate.historySearchChanged_ = lambda self, sender: None
    delegate.historySortChanged_ = lambda self, sender: None
    delegate.historyBookmarkFilter_ = lambda self, sender: None
    delegate.showWelcome_ = lambda self, sender: None
    delegate.showRowMenu_ = lambda self, sender: None
    delegate.bookmarkSession_ = lambda self, sender: None
    delegate.unbookmarkSession_ = lambda self, sender: None
    delegate.openClaudeUsage_ = lambda self, sender: None
    delegate.openClaudeAiUsage_ = lambda self, sender: None
    delegate.jumpToSession_ = lambda self, sender: None
    delegate.viewAuditLog_ = lambda self, sender: None
    delegate.openRepo_ = lambda self, sender: None
    delegate.testNotification_ = lambda self, sender: None
    delegate.testSound_ = lambda self, sender: None
    return delegate


class TestSettingsPane:
    @patch("claudewatch.ui.preferences.panes.settings.features")
    def test_renders_without_crash(self, mock_features: MagicMock) -> None:
        from claudewatch.ui.preferences.panes.settings import SettingsPane

        mock_features.get_all.return_value = []
        mock_features.is_enabled.return_value = True
        pane = SettingsPane(_make_delegate(), 490, 620)
        view = pane.build()
        assert isinstance(view, NSView)

    @patch("claudewatch.ui.preferences.panes.settings.features")
    def test_renders_with_features(self, mock_features: MagicMock) -> None:
        from claudewatch.backend.core.features import Feature
        from claudewatch.ui.preferences.panes.settings import SettingsPane

        mock_features.get_all.return_value = [
            Feature(key="test_feature", description="Test", default_enabled=True),
        ]
        mock_features.is_enabled.return_value = True
        mock_features.get_facet.return_value = None
        pane = SettingsPane(_make_delegate(), 490, 620)
        view = pane.build()
        assert isinstance(view, NSView)


class TestUsagePane:
    @patch("claudewatch.ui.preferences.panes.usage.get_history_service")
    @patch("claudewatch.ui.preferences.panes.usage.get_usage_service")
    def test_renders_empty(self, mock_usage: MagicMock, mock_history: MagicMock) -> None:
        from claudewatch.ui.preferences.panes.usage import UsagePane

        mock_history.return_value.get_all.return_value = []
        pane = UsagePane(_make_delegate(), 490, 620)
        view = pane.build()
        assert isinstance(view, NSView)


class TestGuidePane:
    def test_renders_without_crash(self) -> None:
        from claudewatch.ui.preferences.panes.guide import GuidePane

        pane = GuidePane(_make_delegate(), 490, 620)
        view = pane.build()
        assert isinstance(view, NSView)


class TestAboutPane:
    def test_renders_without_crash(self) -> None:
        from claudewatch.ui.preferences.panes.about import AboutPane

        pane = AboutPane(_make_delegate(), 490, 620)
        view = pane.build()
        assert isinstance(view, NSView)


class TestSessionsPane:
    @patch("claudewatch.ui.preferences.panes.sessions.get_history_service")
    def test_renders_without_crash(self, mock_history: MagicMock) -> None:
        from claudewatch.ui.preferences.panes.sessions import SessionsPane

        mock_history.return_value.get_all.return_value = []
        pane = SessionsPane(_make_delegate(), 490, 620)
        view = pane.build()
        assert isinstance(view, NSView)
