"""Tests for the menubar resume handler's precondition validation."""

from unittest.mock import MagicMock, patch

_MOD = "claudewatch.ui.menubar"

_SID = "12345678-1234-1234-1234-123456789abc"
_CWD = "/Users/dev/myapp"


def _invoke(session_id: str, cwd: str, log_service: MagicMock) -> MagicMock:
    from claudewatch.ui.menubar import ClaudeWatchApp

    handler = ClaudeWatchApp._make_resume_handler(MagicMock(), session_id, cwd)
    with (
        patch(f"{_MOD}.get_session_log_service", return_value=log_service),
        patch(f"{_MOD}.open_terminal_and_run") as mock_open,
    ):
        handler(None)
    return mock_open


class TestResumePrecondition:
    def test_aborts_when_sessions_own_jsonl_is_gone(self) -> None:
        """A sibling session's file in the same cwd must not pass validation."""
        svc = MagicMock()
        svc.find_most_recent.return_value = "/fake/sibling-session.jsonl"
        svc.resolve_jsonl.return_value = None
        mock_open = _invoke(_SID, _CWD, svc)
        svc.resolve_jsonl.assert_called_once_with(_CWD, _SID)
        mock_open.assert_not_called()

    def test_resumes_when_sessions_own_jsonl_exists(self) -> None:
        svc = MagicMock()
        svc.resolve_jsonl.return_value = f"/fake/{_SID}.jsonl"
        mock_open = _invoke(_SID, _CWD, svc)
        mock_open.assert_called_once_with(f"claude -r {_SID}", _CWD)

    def test_rejects_non_uuid_session_id(self) -> None:
        svc = MagicMock()
        mock_open = _invoke("not-a-uuid; rm -rf ~", _CWD, svc)
        svc.resolve_jsonl.assert_not_called()
        mock_open.assert_not_called()
