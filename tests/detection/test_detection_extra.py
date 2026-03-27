"""Extra tests for detection.py — idle detection and session ID lookup."""

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
    _extract_prompt_info,
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
        os.utime(jsonl, (time.time() - 10, time.time() - 10))
        tail = jsonl.read_text()

        svc = _make_detection_service(find_most_recent=str(jsonl), read_tail=tail)
        result = svc._check_jsonl_for_idle("/Users/dev/myapp")
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
        os.utime(jsonl, (time.time() - 10, time.time() - 10))
        tail = jsonl.read_text()

        svc = _make_detection_service(find_most_recent=str(jsonl), read_tail=tail)
        result = svc._check_jsonl_for_idle("/Users/dev/myapp")
        assert result == SessionStatus.WORKING

    def test_returns_working_when_recently_modified(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
            ],
        )
        # File is fresh — should return WORKING even though last msg is assistant
        tail = jsonl.read_text()

        svc = _make_detection_service(find_most_recent=str(jsonl), read_tail=tail)
        result = svc._check_jsonl_for_idle("/Users/dev/myapp")
        assert result == SessionStatus.WORKING

    def test_returns_working_when_no_jsonl(self):
        svc = _make_detection_service(find_most_recent=None)
        result = svc._check_jsonl_for_idle("/Users/dev/myapp")
        assert result == SessionStatus.WORKING

    def test_returns_working_when_empty_jsonl(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text("")
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        svc = _make_detection_service(find_most_recent=str(jsonl), read_tail="")
        result = svc._check_jsonl_for_idle("/Users/dev/myapp")
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
        os.utime(jsonl, (time.time() - 10, time.time() - 10))
        tail = jsonl.read_text()

        svc = _make_detection_service(find_most_recent=str(jsonl), read_tail=tail)
        result = svc._check_jsonl_for_idle("/Users/dev/myapp")
        assert result == SessionStatus.IDLE


class TestDetermineStatus:
    def test_idle_indicator(self):
        assert _determine_status("myapp — ✳ Claude Code") == SessionStatus.IDLE

    def test_working_default(self):
        assert _determine_status("myapp — ● Running tests") == SessionStatus.WORKING

    def test_empty_title(self):
        assert _determine_status("") == SessionStatus.WORKING


class TestExtractPromptInfo:
    def test_extracts_prompt_context(self):
        buf = "some output\n⏺ Bash: ls -la\n  Allow once  \n  Allow always  "
        result = _extract_prompt_info(buf)
        assert "Bash" in result.one_line or "ls" in result.context

    def test_no_prompt_returns_empty(self):
        buf = "just regular output\nno prompts here"
        result = _extract_prompt_info(buf)
        assert result.one_line == ""
        assert result.context == ""

    def test_truncates_long_one_liner(self):
        long_cmd = "x" * 200
        buf = f"⏺ {long_cmd}\n  Allow once  "
        result = _extract_prompt_info(buf)
        assert len(result.one_line) <= 80
        assert result.one_line.endswith("...")


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
