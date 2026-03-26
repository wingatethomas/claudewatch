"""Tests for claudewatch.backend.bookmark.service.BookmarkService."""

from unittest.mock import patch

from claudewatch.backend.bookmark.service import BookmarkService
from claudewatch.backend.core.dto import BookmarkDTO


class TestBookmarkService:
    """BookmarkService delegates to the bookmarks repository."""

    def setup_method(self) -> None:
        self.svc = BookmarkService()

    @patch("claudewatch.backend.bookmark.service.bookmarks_repo")
    def test_add_delegates_to_repo(self, mock_repo):
        self.svc.add("sid-1", "myproject", "/tmp/cwd", "a note")
        mock_repo.add_bookmark.assert_called_once_with("sid-1", "myproject", "/tmp/cwd", "a note")

    @patch("claudewatch.backend.bookmark.service.bookmarks_repo")
    def test_remove_delegates_to_repo(self, mock_repo):
        self.svc.remove("/tmp/cwd")
        mock_repo.remove_bookmark.assert_called_once_with("/tmp/cwd")

    @patch("claudewatch.backend.bookmark.service.bookmarks_repo")
    def test_get_all_returns_bookmark_dtos(self, mock_repo):
        mock_repo.get_bookmarks.return_value = [
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
        result = self.svc.get_all()
        assert len(result) == 2
        assert all(isinstance(p, BookmarkDTO) for p in result)
        assert result[0].session_id == "s1"
        assert result[0].cwd == "/tmp/a"
        assert result[1].note == "n2"

    @patch("claudewatch.backend.bookmark.service.bookmarks_repo")
    def test_get_all_handles_empty(self, mock_repo):
        mock_repo.get_bookmarks.return_value = []
        assert self.svc.get_all() == []

    @patch("claudewatch.backend.bookmark.service.bookmarks_repo")
    def test_get_all_handles_missing_fields(self, mock_repo):
        mock_repo.get_bookmarks.return_value = [{"session_id": "s1"}]
        result = self.svc.get_all()
        assert len(result) == 1
        assert result[0].session_id == "s1"
        assert result[0].project == ""
        assert result[0].cwd == ""
        assert result[0].note == ""
        assert result[0].timestamp == ""

    @patch("claudewatch.backend.bookmark.service.bookmarks_repo")
    def test_get_bookmarked_cwds_delegates_to_repo(self, mock_repo):
        mock_repo.get_bookmarked_cwds.return_value = {"/tmp/a", "/tmp/b"}
        result = self.svc.get_bookmarked_cwds()
        assert result == {"/tmp/a", "/tmp/b"}
        mock_repo.get_bookmarked_cwds.assert_called_once()

    @patch("claudewatch.backend.bookmark.service.bookmarks_repo")
    def test_get_all_returns_frozen_dtos(self, mock_repo):
        mock_repo.get_bookmarks.return_value = [
            {
                "session_id": "s1",
                "project": "proj",
                "cwd": "/tmp/a",
                "note": "n1",
                "timestamp": "2025-01-01T00:00:00+00:00",
            },
        ]
        result = self.svc.get_all()
        bookmark = result[0]
        # BookmarkDTO is frozen — assignment should raise
        try:
            bookmark.session_id = "changed"  # type: ignore[misc]
            raise AssertionError("Expected FrozenInstanceError")
        except AttributeError:
            pass
