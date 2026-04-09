"""Extra tests for detection.py — idle detection, pending tool, and session ID lookup."""

import json
import os
import time
from unittest.mock import MagicMock

from claudewatch.backend.core.models import SessionStatus
from claudewatch.backend.core.process.service import ProcessService
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.detection.service import (
    DetectionService,
    _determine_status,
)


def _write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_detection_service(
    find_most_recent: str | None = None,
    read_tail: str = "",
    get_session_id: str = "",
) -> DetectionService:
    """Create a DetectionService with mocked dependencies."""
    mock_log = MagicMock(spec=SessionLogService)
    mock_log.find_most_recent.return_value = find_most_recent
    mock_log.read_tail.return_value = read_tail
    mock_log.get_session_id.return_value = get_session_id
    mock_proc = MagicMock(spec=ProcessService)
    return DetectionService(mock_proc, mock_log)


class TestCheckJsonlForIdle:
    def test_returns_idle_when_last_is_assistant(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {"type": "user", "message": {"content": "hello"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
            ],
        )
        tail = jsonl.read_text()

        svc = _make_detection_service()
        result = svc._check_jsonl_for_idle(tail)
        assert result == SessionStatus.IDLE

    def test_returns_working_when_last_is_user(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
                {"type": "user", "message": {"content": "do something"}},
            ],
        )
        tail = jsonl.read_text()

        svc = _make_detection_service()
        result = svc._check_jsonl_for_idle(tail)
        assert result == SessionStatus.WORKING

    def test_returns_working_when_empty(self):
        svc = _make_detection_service()
        result = svc._check_jsonl_for_idle("")
        assert result == SessionStatus.WORKING

    def test_skips_non_user_assistant_types(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {"type": "assistant", "message": {"content": []}},
                {"type": "system", "message": {}},
                {"type": "progress", "data": {}},
            ],
        )
        tail = jsonl.read_text()

        svc = _make_detection_service()
        result = svc._check_jsonl_for_idle(tail)
        assert result == SessionStatus.IDLE


class TestReadJsonlTail:
    def test_returns_empty_when_no_path(self):
        svc = _make_detection_service()
        tail, is_fresh = svc._read_jsonl_tail(None)
        assert tail == ""
        assert is_fresh is False

    def test_returns_fresh_when_recently_modified(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [{"type": "assistant", "message": {"content": []}}])
        # File is fresh (just created)
        svc = _make_detection_service(read_tail=jsonl.read_text())
        tail, is_fresh = svc._read_jsonl_tail(str(jsonl))
        assert is_fresh is True
        assert tail != ""

    def test_returns_not_fresh_when_old(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [{"type": "assistant", "message": {"content": []}}])
        os.utime(jsonl, (time.time() - 10, time.time() - 10))
        svc = _make_detection_service(read_tail=jsonl.read_text())
        tail, is_fresh = svc._read_jsonl_tail(str(jsonl))
        assert is_fresh is False
        assert tail != ""


class TestCheckJsonlForPendingTool:
    def test_returns_empty_when_no_tail(self):
        svc = _make_detection_service()
        result = svc._check_jsonl_for_pending_tool("")
        assert result.has_pending is False

    def test_detects_pending_tool_use(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}],
                    },
                },
            ],
        )
        tail = jsonl.read_text()

        svc = _make_detection_service()
        result = svc._check_jsonl_for_pending_tool(tail)
        assert result.has_pending is True
        assert "Bash" in result.one_line

    def test_resolved_tool_not_pending(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "content": [{"type": "tool_result", "tool_use_id": "123", "content": "ok"}],
                    },
                },
            ],
        )
        tail = jsonl.read_text()

        svc = _make_detection_service()
        result = svc._check_jsonl_for_pending_tool(tail)
        assert result.has_pending is False


class TestDetermineStatus:
    def test_idle_indicator(self):
        assert _determine_status("myapp — ✳ Claude Code") == SessionStatus.IDLE

    def test_working_default(self):
        assert _determine_status("myapp — ● Running tests") == SessionStatus.WORKING

    def test_empty_title(self):
        assert _determine_status("") == SessionStatus.WORKING


class TestGetSessionId:
    def test_returns_session_id(self):
        svc = _make_detection_service(
            find_most_recent="/fake/abc-123-def.jsonl",
            get_session_id="abc-123-def",
        )
        result = svc._get_session_id("/Users/dev/myapp")
        assert result == "abc-123-def"

    def test_returns_empty_when_no_dir(self):
        svc = _make_detection_service(find_most_recent=None)
        result = svc._get_session_id("/Users/dev/myapp")
        assert result == ""

    def test_returns_most_recent(self):
        svc = _make_detection_service(
            find_most_recent="/fake/new-session.jsonl",
            get_session_id="new-session",
        )
        result = svc._get_session_id("/Users/dev/myapp")
        assert result == "new-session"
