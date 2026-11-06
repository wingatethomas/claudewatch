"""Tests for claudewatch.backend.history.service.HistoryService."""

from unittest.mock import patch

from claudewatch.backend.core.dto import HistoryEntryDTO
from claudewatch.backend.history.service import HistoryService


class TestHistoryService:
    """HistoryService delegates to the history repository."""

    def setup_method(self) -> None:
        self.svc = HistoryService()

    @patch("claudewatch.backend.history.service.history_repo")
    def test_record_delegates_to_repo(self, mock_repo):
        self.svc.record("sid-1", "myproject", "/tmp/cwd", "opus-4", "Terminal")
        mock_repo.record_session.assert_called_once_with("sid-1", "myproject", "/tmp/cwd", "opus-4", "Terminal", "")

    @patch("claudewatch.backend.history.service.history_repo")
    def test_get_all_returns_history_entry_dtos(self, mock_repo):
        mock_repo.get_history.return_value = [
            HistoryEntryDTO(
                session_id="s1",
                project="proj",
                cwd="/tmp/a",
                model="opus-4",
                host_app="Terminal",
                ended_at="2025-01-01T00:00:00+00:00",
            ),
            HistoryEntryDTO(
                session_id="s2",
                project="proj2",
                cwd="/tmp/b",
                model="sonnet-4",
                host_app="VSCode",
                ended_at="2025-01-02T00:00:00+00:00",
            ),
        ]
        result = self.svc.get_all()
        assert len(result) == 2
        assert all(isinstance(e, HistoryEntryDTO) for e in result)
        assert result[0].session_id == "s1"
        assert result[0].model == "opus-4"
        assert result[1].host_app == "VSCode"

    @patch("claudewatch.backend.history.service.history_repo")
    def test_get_all_handles_empty(self, mock_repo):
        mock_repo.get_history.return_value = []
        assert self.svc.get_all() == []

    @patch("claudewatch.backend.history.service.history_repo")
    def test_get_all_handles_empty_fields(self, mock_repo):
        mock_repo.get_history.return_value = [
            HistoryEntryDTO(session_id="s1", project="", cwd="", model="", host_app="", ended_at=""),
        ]
        result = self.svc.get_all()
        assert len(result) == 1
        assert result[0].session_id == "s1"
        assert result[0].project == ""
        assert result[0].cwd == ""
        assert result[0].model == ""
        assert result[0].host_app == ""
        assert result[0].ended_at == ""

    @patch("claudewatch.backend.history.service.history_repo")
    def test_remove_delegates_to_repo(self, mock_repo):
        self.svc.remove("sid-1", "/tmp/cwd")
        mock_repo.remove_history_entry.assert_called_once_with("sid-1", "/tmp/cwd")

    @patch("claudewatch.backend.history.service.history_repo")
    def test_get_all_caches_after_first_call(self, mock_repo):
        mock_repo.get_history.return_value = []
        self.svc.get_all()
        self.svc.get_all()
        self.svc.get_all()
        assert mock_repo.get_history.call_count == 1

    @patch("claudewatch.backend.history.service.history_repo")
    def test_record_invalidates_cache(self, mock_repo):
        mock_repo.get_history.return_value = []
        self.svc.get_all()
        self.svc.record("sid", "proj", "/tmp/c", "model", "Terminal")
        self.svc.get_all()
        assert mock_repo.get_history.call_count == 2

    @patch("claudewatch.backend.history.service.history_repo")
    def test_remove_invalidates_cache(self, mock_repo):
        mock_repo.get_history.return_value = []
        self.svc.get_all()
        self.svc.remove("sid-1", "/tmp/c")
        self.svc.get_all()
        assert mock_repo.get_history.call_count == 2

    @patch("claudewatch.backend.history.service.history_repo")
    def test_warm_populates_cache(self, mock_repo):
        mock_repo.get_history.return_value = []
        self.svc.warm()
        self.svc.get_all()
        assert mock_repo.get_history.call_count == 1

    @patch("claudewatch.backend.history.service.history_repo")
    def test_get_all_returns_independent_list(self, mock_repo):
        mock_repo.get_history.return_value = [
            HistoryEntryDTO(session_id="s1", project="p", cwd="/tmp/a", model="m", host_app="Terminal", ended_at=""),
        ]
        result = self.svc.get_all()
        result.clear()
        assert len(self.svc.get_all()) == 1

    @patch("claudewatch.backend.history.service.history_repo")
    def test_get_all_returns_frozen_dtos(self, mock_repo):
        mock_repo.get_history.return_value = [
            HistoryEntryDTO(
                session_id="s1",
                project="proj",
                cwd="/tmp/a",
                model="opus-4",
                host_app="Terminal",
                ended_at="2025-01-01T00:00:00+00:00",
            ),
        ]
        result = self.svc.get_all()
        entry = result[0]
        # HistoryEntryDTO is frozen — assignment should raise
        try:
            entry.session_id = "changed"  # type: ignore[misc]
            raise AssertionError("Expected FrozenInstanceError")
        except AttributeError:
            pass


class TestRecentlyFinished:
    """recently_finished filters ended auto sessions by window."""

    def setup_method(self) -> None:
        self.svc = HistoryService()

    def _entry(self, sid: str, ended_at: str, mode: str = "auto") -> HistoryEntryDTO:
        return HistoryEntryDTO(
            session_id=sid,
            project="p",
            cwd="/tmp/p",
            model="m",
            host_app="Terminal",
            ended_at=ended_at,
            permission_mode=mode,
        )

    @patch("claudewatch.backend.history.service.history_repo")
    def test_within_window_included(self, mock_repo):
        from datetime import UTC, datetime, timedelta

        now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
        fresh = self._entry("s1", (now - timedelta(minutes=10)).isoformat())
        stale = self._entry("s2", (now - timedelta(hours=2)).isoformat())
        mock_repo.get_history.return_value = [fresh, stale]
        result = self.svc.recently_finished(now=now)
        assert [e.session_id for e in result] == ["s1"]

    @patch("claudewatch.backend.history.service.history_repo")
    def test_non_auto_excluded(self, mock_repo):
        from datetime import UTC, datetime, timedelta

        now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
        default = self._entry("s1", (now - timedelta(minutes=10)).isoformat(), mode="default")
        legacy = self._entry("s2", (now - timedelta(minutes=10)).isoformat(), mode="")
        mock_repo.get_history.return_value = [default, legacy]
        assert self.svc.recently_finished(now=now) == []

    @patch("claudewatch.backend.history.service.history_repo")
    def test_bad_timestamp_and_missing_sid_tolerated(self, mock_repo):
        from datetime import UTC, datetime

        now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
        bad_ts = self._entry("s1", "not-a-date")
        no_sid = self._entry("", now.isoformat())
        mock_repo.get_history.return_value = [bad_ts, no_sid]
        assert self.svc.recently_finished(now=now) == []

    @patch("claudewatch.backend.history.service.history_repo")
    def test_backfill_invalidates_cache_only_on_change(self, mock_repo):
        mock_repo.get_history.return_value = []
        mock_repo.backfill_recent.return_value = 0
        self.svc.get_all()
        self.svc.backfill_recent()
        self.svc.get_all()
        assert mock_repo.get_history.call_count == 1
        mock_repo.backfill_recent.return_value = 2
        self.svc.backfill_recent()
        self.svc.get_all()
        assert mock_repo.get_history.call_count == 2
