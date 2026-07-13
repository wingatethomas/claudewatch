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
    delegate.removePermission_ = lambda self, sender: None
    delegate.clearPermissions_ = lambda self, sender: None
    delegate.removeDangerousPermissions_ = lambda self, sender: None
    delegate.uninstallPlugin_ = lambda self, sender: None
    delegate.openBlocklistSource_ = lambda self, sender: None
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


class TestSecurityPane:
    @patch("claudewatch.ui.preferences.panes.security.get_security_service")
    def test_renders_empty_config(self, mock_svc: MagicMock) -> None:
        from claudewatch.backend.security.models import ConfigSnapshot
        from claudewatch.ui.preferences.panes.security import SecurityPane

        repo = MagicMock()
        repo.capture_snapshot.return_value = ConfigSnapshot()
        repo.get_blocklist_entries.return_value = []
        repo.get_global_permissions.return_value = ("", [])
        repo.get_all_project_permissions.return_value = []
        mock_svc.return_value.repository = repo

        pane = SecurityPane(_make_delegate(), 490, 620)
        view = pane.build()
        assert isinstance(view, NSView)

    @patch("claudewatch.ui.preferences.panes.security.features")
    @patch("claudewatch.ui.preferences.panes.security.get_security_service")
    def test_renders_with_data(self, mock_svc: MagicMock, mock_features: MagicMock) -> None:
        from claudewatch.backend.security.models import ConfigSnapshot
        from claudewatch.ui.preferences.panes.security import SecurityPane

        mock_features.get_facet.return_value = True

        snapshot = ConfigSnapshot(
            plugins_installed={"plugins": {"test-plugin@official": [{"scope": "user", "installedAt": "2026-01-01"}]}},
            plugins_blocklist={
                "fetchedAt": "2026-03-31",
                "plugins": [{"plugin": "bad@evil", "reason": "security", "text": "dangerous"}],
            },
            settings={"enabledPlugins": {"test-plugin@official": True}},
            policy_limits={"restrictions": {"allow_remote_control": {"allowed": False}}},
            known_marketplaces={"official": {"source": {"repo": "anthropics/test"}}},
        )
        repo = MagicMock()
        repo.capture_snapshot.return_value = snapshot
        repo.get_blocklist_entries.return_value = [{"plugin": "bad@evil", "reason": "security", "text": "dangerous"}]
        repo.get_global_permissions.return_value = ("/fake/path", ["Bash(python3:*)", "Bash(ls:*)"])
        repo.get_all_project_permissions.return_value = [("myproject", "/fake/proj", ["Bash(git:*)"])]
        repo.get_plugin_keys.return_value = {"test-plugin@official"}
        repo.get_policy_value.return_value = False
        mock_svc.return_value.repository = repo

        pane = SecurityPane(_make_delegate(), 490, 620)
        view = pane.build()
        assert isinstance(view, NSView)

    @patch("claudewatch.ui.preferences.panes.security.get_security_service")
    def test_renders_without_blocklist(self, mock_svc: MagicMock) -> None:
        from claudewatch.backend.security.models import ConfigSnapshot
        from claudewatch.ui.preferences.panes.security import SecurityPane

        snapshot = ConfigSnapshot(
            plugins_installed={"plugins": {}},
            policy_limits={"allow_remote_control": False},
        )
        repo = MagicMock()
        repo.capture_snapshot.return_value = snapshot
        repo.get_blocklist_entries.return_value = []
        repo.get_global_permissions.return_value = ("", [])
        repo.get_all_project_permissions.return_value = []
        repo.get_policy_value.return_value = False
        mock_svc.return_value.repository = repo

        pane = SecurityPane(_make_delegate(), 490, 620)
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

    @patch("claudewatch.ui.preferences.panes.sessions.get_usage_service")
    @patch("claudewatch.ui.preferences.panes.sessions.get_summary_service")
    @patch("claudewatch.ui.preferences.panes.sessions.get_bookmark_service")
    @patch("claudewatch.ui.preferences.panes.sessions.get_history_service")
    def test_renders_with_duplicate_project_names(
        self,
        mock_history: MagicMock,
        mock_bookmark: MagicMock,
        mock_summary: MagicMock,
        mock_usage: MagicMock,
    ) -> None:
        from claudewatch.backend.core.dto import HistoryEntryDTO, TokenUsageDTO
        from claudewatch.ui.preferences.panes.sessions import SessionsPane

        mock_history.return_value.get_all.return_value = [
            HistoryEntryDTO(
                session_id="s1",
                project="api",
                cwd="/Users/dev/backend/api",
                model="claude-opus-4-6",
                host_app="Terminal",
                ended_at="2026-05-20T12:00:00",
            ),
            HistoryEntryDTO(
                session_id="s2",
                project="api",
                cwd="/Users/dev/frontend/api",
                model="",
                host_app="Terminal",
                ended_at="2026-05-20T13:00:00",
            ),
        ]
        mock_bookmark.return_value.get_bookmarked_cwds.return_value = set()
        mock_summary.return_value.get_cached.return_value = ""
        mock_summary.return_value.get_cached_summary.return_value = ""
        mock_usage.return_value.get_tokens.return_value = TokenUsageDTO(0, 0, 0, 0)
        mock_usage.return_value.get_model.return_value = "claude-sonnet-4-6"

        pane = SessionsPane(_make_delegate(), 490, 620)
        view = pane.build()
        assert isinstance(view, NSView)


class TestDisambiguateProjects:
    def test_unique_names_kept_as_is(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import disambiguate_projects

        entries = [
            {"project": "myapp", "cwd": "/Users/dev/myapp"},
            {"project": "tools", "cwd": "/Users/dev/tools"},
        ]
        labels = disambiguate_projects(entries)
        assert labels["/Users/dev/myapp"] == "myapp"
        assert labels["/Users/dev/tools"] == "tools"

    def test_duplicate_names_prepend_parent(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import disambiguate_projects

        entries = [
            {"project": "api", "cwd": "/Users/dev/backend/api"},
            {"project": "api", "cwd": "/Users/dev/frontend/api"},
            {"project": "webtools", "cwd": "/Users/dev/webtools"},
        ]
        labels = disambiguate_projects(entries)
        assert labels["/Users/dev/backend/api"] == "backend/api"
        assert labels["/Users/dev/frontend/api"] == "frontend/api"
        assert labels["/Users/dev/webtools"] == "webtools"

    def test_multiple_sessions_same_cwd_share_label(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import disambiguate_projects

        entries = [
            {"project": "api", "cwd": "/Users/dev/api"},
            {"project": "api", "cwd": "/Users/dev/api"},
        ]
        labels = disambiguate_projects(entries)
        assert labels == {"/Users/dev/api": "api"}

    def test_missing_cwd_is_skipped(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import disambiguate_projects

        entries = [
            {"project": "api", "cwd": ""},
            {"project": "api", "cwd": "/Users/dev/api"},
        ]
        labels = disambiguate_projects(entries)
        assert labels == {"/Users/dev/api": "api"}

    def test_empty_input(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import disambiguate_projects

        assert disambiguate_projects([]) == {}


class TestResolveModelLabel:
    def test_known_model_id_maps_to_display_name(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import _resolve_model_label

        svc = MagicMock()
        assert _resolve_model_label("claude-opus-4-6", "/tmp/proj", svc) == "opus 4.6"
        svc.get_model.assert_not_called()

    def test_new_family_id_derives_label(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import _resolve_model_label

        svc = MagicMock()
        assert _resolve_model_label("claude-future-99", "/tmp/proj", svc) == "future 99"
        svc.get_model.assert_not_called()

    def test_empty_model_falls_back_to_usage_service(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import _resolve_model_label

        svc = MagicMock()
        svc.get_model.return_value = "claude-sonnet-4-6"
        assert _resolve_model_label("", "/tmp/proj", svc) == "sonnet 4.6"
        svc.get_model.assert_called_once_with("/tmp/proj", "")

    def test_fallback_passes_session_id(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import _resolve_model_label

        svc = MagicMock()
        svc.get_model.return_value = "claude-sonnet-4-6"
        assert _resolve_model_label("", "/tmp/proj", svc, "sid-a") == "sonnet 4.6"
        svc.get_model.assert_called_once_with("/tmp/proj", "sid-a")

    def test_fallback_service_id_derives_label(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import _resolve_model_label

        svc = MagicMock()
        svc.get_model.return_value = "claude-future-99"
        assert _resolve_model_label("", "/tmp/proj", svc) == "future 99"

    def test_empty_model_and_no_cwd_returns_empty(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import _resolve_model_label

        svc = MagicMock()
        assert _resolve_model_label("", "", svc) == ""
        svc.get_model.assert_not_called()

    def test_usage_service_failure_returns_empty(self) -> None:
        from claudewatch.ui.preferences.panes.sessions import _resolve_model_label

        svc = MagicMock()
        svc.get_model.side_effect = OSError("disk error")
        assert _resolve_model_label("", "/tmp/proj", svc) == ""
