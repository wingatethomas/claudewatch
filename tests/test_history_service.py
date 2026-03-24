"""Tests for claudewatch.backend.services.history.HistoryService."""

from unittest.mock import patch

from claudewatch.backend.core.dto import HistoryEntryDTO
from claudewatch.backend.services.history import HistoryService


class TestHistoryService:
    """HistoryService delegates to the history repository."""

    def setup_method(self) -> None:
        self.svc = HistoryService()

    @patch("claudewatch.backend.services.history.history_repo")
    def test_record_delegates_to_repo(self, mock_repo):
        self.svc.record("sid-1", "myproject", "/tmp/cwd", "opus-4", "Terminal")
        mock_repo.record_session.assert_called_once_with(
            "sid-1", "myproject", "/tmp/cwd", "opus-4", "Terminal"
        )

    @patch("claudewatch.backend.services.history.history_repo")
    def test_get_all_returns_history_entry_dtos(self, mock_repo):
        mock_repo.get_history.return_value = [
            {
                "session_id": "s1",
                "project": "proj",
                "cwd": "/tmp/a",
                "model": "opus-4",
                "host_app": "Terminal",
                "ended_at": "2025-01-01T00:00:00+00:00",
            },
            {
                "session_id": "s2",
                "project": "proj2",
                "cwd": "/tmp/b",
                "model": "sonnet-4",
                "host_app": "VSCode",
                "ended_at": "2025-01-02T00:00:00+00:00",
            },
        ]
        result = self.svc.get_all()
        assert len(result) == 2
        assert all(isinstance(e, HistoryEntryDTO) for e in result)
        assert result[0].session_id == "s1"
        assert result[0].model == "opus-4"
        assert result[1].host_app == "VSCode"

    @patch("claudewatch.backend.services.history.history_repo")
    def test_get_all_handles_empty(self, mock_repo):
        mock_repo.get_history.return_value = []
        assert self.svc.get_all() == []

    @patch("claudewatch.backend.services.history.history_repo")
    def test_get_all_handles_missing_fields(self, mock_repo):
        mock_repo.get_history.return_value = [{"session_id": "s1"}]
        result = self.svc.get_all()
        assert len(result) == 1
        assert result[0].session_id == "s1"
        assert result[0].project == ""
        assert result[0].cwd == ""
        assert result[0].model == ""
        assert result[0].host_app == ""
        assert result[0].ended_at == ""

    @patch("claudewatch.backend.services.history.history_repo")
    def test_remove_delegates_to_repo(self, mock_repo):
        self.svc.remove("/tmp/cwd")
        mock_repo.remove_history_entry.assert_called_once_with("/tmp/cwd")

    @patch("claudewatch.backend.services.history.history_repo")
    def test_get_all_returns_frozen_dtos(self, mock_repo):
        mock_repo.get_history.return_value = [
            {
                "session_id": "s1",
                "project": "proj",
                "cwd": "/tmp/a",
                "model": "opus-4",
                "host_app": "Terminal",
                "ended_at": "2025-01-01T00:00:00+00:00",
            },
        ]
        result = self.svc.get_all()
        entry = result[0]
        # HistoryEntryDTO is frozen — assignment should raise
        try:
            entry.session_id = "changed"  # type: ignore[misc]
            raise AssertionError("Expected FrozenInstanceError")
        except AttributeError:
            pass
