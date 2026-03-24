"""Tests for claudewatch.backend.services.bookmark.BookmarkService."""

from unittest.mock import patch

from claudewatch.backend.core.dto import PinDTO
from claudewatch.backend.services.bookmark import BookmarkService


class TestBookmarkService:
    """BookmarkService delegates to the bookmarks repository."""

    def setup_method(self) -> None:
        self.svc = BookmarkService()

    @patch("claudewatch.backend.services.bookmark.bookmarks_repo")
    def test_pin_delegates_to_repo(self, mock_repo):
        self.svc.pin("sid-1", "myproject", "/tmp/cwd", "a note")
        mock_repo.pin_session.assert_called_once_with("sid-1", "myproject", "/tmp/cwd", "a note")

    @patch("claudewatch.backend.services.bookmark.bookmarks_repo")
    def test_unpin_delegates_to_repo(self, mock_repo):
        self.svc.unpin("/tmp/cwd")
        mock_repo.unpin_session.assert_called_once_with("/tmp/cwd")

    @patch("claudewatch.backend.services.bookmark.bookmarks_repo")
    def test_get_pins_returns_pin_dtos(self, mock_repo):
        mock_repo.get_pins.return_value = [
            {
                "session_id": "s1",
                "project": "proj",
                "cwd": "/tmp/a",
                "note": "n1",
                "timestamp": "2025-01-01T00:00:00+00:00",
            },
            {
                "session_id": "s2",
                "project": "proj2",
                "cwd": "/tmp/b",
                "note": "n2",
                "timestamp": "2025-01-02T00:00:00+00:00",
            },
        ]
        result = self.svc.get_pins()
        assert len(result) == 2
        assert all(isinstance(p, PinDTO) for p in result)
        assert result[0].session_id == "s1"
        assert result[0].cwd == "/tmp/a"
        assert result[1].note == "n2"

    @patch("claudewatch.backend.services.bookmark.bookmarks_repo")
    def test_get_pins_handles_empty(self, mock_repo):
        mock_repo.get_pins.return_value = []
        assert self.svc.get_pins() == []

    @patch("claudewatch.backend.services.bookmark.bookmarks_repo")
    def test_get_pins_handles_missing_fields(self, mock_repo):
        mock_repo.get_pins.return_value = [{"session_id": "s1"}]
        result = self.svc.get_pins()
        assert len(result) == 1
        assert result[0].session_id == "s1"
        assert result[0].project == ""
        assert result[0].cwd == ""
        assert result[0].note == ""
        assert result[0].timestamp == ""

    @patch("claudewatch.backend.services.bookmark.bookmarks_repo")
    def test_get_pinned_cwds_delegates_to_repo(self, mock_repo):
        mock_repo.get_pinned_cwds.return_value = {"/tmp/a", "/tmp/b"}
        result = self.svc.get_pinned_cwds()
        assert result == {"/tmp/a", "/tmp/b"}
        mock_repo.get_pinned_cwds.assert_called_once()

    @patch("claudewatch.backend.services.bookmark.bookmarks_repo")
    def test_get_pins_returns_frozen_dtos(self, mock_repo):
        mock_repo.get_pins.return_value = [
            {
                "session_id": "s1",
                "project": "proj",
                "cwd": "/tmp/a",
                "note": "n1",
                "timestamp": "2025-01-01T00:00:00+00:00",
            },
        ]
        result = self.svc.get_pins()
        pin = result[0]
        # PinDTO is frozen — assignment should raise
        try:
            pin.session_id = "changed"  # type: ignore[misc]
            raise AssertionError("Expected FrozenInstanceError")
        except AttributeError:
            pass
