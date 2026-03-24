"""Tests for SessionLogService delegation to jsonl module."""

from unittest.mock import patch

from claudewatch.backend.core.services.session_log import SessionLogService

MODULE = "claudewatch.backend.core.services.session_log.jsonl"


class TestFindMostRecent:
    """Tests for SessionLogService.find_most_recent."""

    def test_delegates_to_find_most_recent_jsonl(self):
        svc = SessionLogService()
        with patch(f"{MODULE}.find_most_recent_jsonl", return_value="/path/to/session.jsonl") as mock:
            result = svc.find_most_recent("/Users/dev/myapp")
        mock.assert_called_once_with("/Users/dev/myapp")
        assert result == "/path/to/session.jsonl"

    def test_returns_none_when_delegate_returns_none(self):
        svc = SessionLogService()
        with patch(f"{MODULE}.find_most_recent_jsonl", return_value=None) as mock:
            result = svc.find_most_recent("/nonexistent")
        mock.assert_called_once_with("/nonexistent")
        assert result is None


class TestIsSafePath:
    """Tests for SessionLogService.is_safe_path."""

    def test_delegates_to_is_safe_jsonl_path(self):
        svc = SessionLogService()
        with patch(f"{MODULE}.is_safe_jsonl_path", return_value=True) as mock:
            result = svc.is_safe_path("/safe/path.jsonl")
        mock.assert_called_once_with("/safe/path.jsonl")
        assert result is True

    def test_returns_false_for_unsafe_path(self):
        svc = SessionLogService()
        with patch(f"{MODULE}.is_safe_jsonl_path", return_value=False) as mock:
            result = svc.is_safe_path("/evil/path.jsonl")
        mock.assert_called_once_with("/evil/path.jsonl")
        assert result is False


class TestReadTail:
    """Tests for SessionLogService.read_tail."""

    def test_delegates_with_default_tail_bytes(self):
        svc = SessionLogService()
        with patch(f"{MODULE}.read_jsonl_tail", return_value="tail content") as mock:
            result = svc.read_tail("/path/to/session.jsonl")
        mock.assert_called_once_with("/path/to/session.jsonl", tail_bytes=10240)
        assert result == "tail content"

    def test_delegates_with_custom_tail_bytes(self):
        svc = SessionLogService()
        with patch(f"{MODULE}.read_jsonl_tail", return_value="short") as mock:
            result = svc.read_tail("/path/to/session.jsonl", tail_bytes=512)
        mock.assert_called_once_with("/path/to/session.jsonl", tail_bytes=512)
        assert result == "short"


class TestReadFull:
    """Tests for SessionLogService.read_full."""

    def test_delegates_to_read_jsonl_full(self):
        svc = SessionLogService()
        lines = ['{"a": 1}\n', '{"b": 2}\n']
        with patch(f"{MODULE}.read_jsonl_full", return_value=lines) as mock:
            result = svc.read_full("/path/to/session.jsonl")
        mock.assert_called_once_with("/path/to/session.jsonl")
        assert result == lines

    def test_returns_empty_list_on_error(self):
        svc = SessionLogService()
        with patch(f"{MODULE}.read_jsonl_full", return_value=[]) as mock:
            result = svc.read_full("/missing.jsonl")
        mock.assert_called_once_with("/missing.jsonl")
        assert result == []


class TestGetSessionId:
    """Tests for SessionLogService.get_session_id."""

    def test_delegates_to_get_session_id_from_path(self):
        svc = SessionLogService()
        with patch(f"{MODULE}.get_session_id_from_path", return_value="abc-123-def") as mock:
            result = svc.get_session_id("/path/to/abc-123-def.jsonl")
        mock.assert_called_once_with("/path/to/abc-123-def.jsonl")
        assert result == "abc-123-def"

    def test_handles_bare_filename(self):
        svc = SessionLogService()
        with patch(f"{MODULE}.get_session_id_from_path", return_value="session") as mock:
            result = svc.get_session_id("session.jsonl")
        mock.assert_called_once_with("session.jsonl")
        assert result == "session"
