"""Extra tests for detection.py — idle detection and session ID lookup."""

import json
import os
import time
from unittest.mock import patch

from claudewatch.backend.models import SessionStatus
from claudewatch.backend.services.detection import (
    _check_jsonl_for_idle,
    _determine_status,
    _extract_prompt_info,
    _get_session_id,
)


def _write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestCheckJsonlForIdle:
    def test_returns_idle_when_last_is_assistant(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {"type": "user", "message": {"content": "hello"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
            ],
        )
        # Set mtime to be old enough (>5s threshold)
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _check_jsonl_for_idle("/Users/dev/myapp")
        assert result == SessionStatus.IDLE

    def test_returns_working_when_last_is_user(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
                {"type": "user", "message": {"content": "do something"}},
            ],
        )
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _check_jsonl_for_idle("/Users/dev/myapp")
        assert result == SessionStatus.WORKING

    def test_returns_working_when_recently_modified(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
            ],
        )
        # File is fresh — should return WORKING even though last msg is assistant

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _check_jsonl_for_idle("/Users/dev/myapp")
        assert result == SessionStatus.WORKING

    def test_returns_working_when_no_jsonl(self, tmp_path):
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            result = _check_jsonl_for_idle("/Users/dev/myapp")
        assert result == SessionStatus.WORKING

    def test_returns_working_when_empty_jsonl(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        jsonl.write_text("")
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _check_jsonl_for_idle("/Users/dev/myapp")
        assert result == SessionStatus.WORKING

    def test_skips_non_user_assistant_types(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {"type": "assistant", "message": {"content": []}},
                {"type": "system", "message": {}},
                {"type": "progress", "data": {}},
            ],
        )
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _check_jsonl_for_idle("/Users/dev/myapp")
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
        one_line, context = _extract_prompt_info(buf)
        assert "Bash" in one_line or "ls" in context

    def test_no_prompt_returns_empty(self):
        buf = "just regular output\nno prompts here"
        one_line, context = _extract_prompt_info(buf)
        assert one_line == ""
        assert context == ""

    def test_truncates_long_one_liner(self):
        long_cmd = "x" * 200
        buf = f"⏺ {long_cmd}\n  Allow once  "
        one_line, _ = _extract_prompt_info(buf)
        assert len(one_line) <= 80
        assert one_line.endswith("...")


class TestGetSessionId:
    def test_returns_session_id(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        (proj_dir / "abc-123-def.jsonl").write_text("{}\n")

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _get_session_id("/Users/dev/myapp")
        assert result == "abc-123-def"

    def test_returns_empty_when_no_dir(self, tmp_path):
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            result = _get_session_id("/Users/dev/myapp")
        assert result == ""

    def test_returns_most_recent(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        old = proj_dir / "old-session.jsonl"
        old.write_text("{}\n")
        os.utime(old, (1000, 1000))
        new = proj_dir / "new-session.jsonl"
        new.write_text("{}\n")
        os.utime(new, (2000, 2000))

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _get_session_id("/Users/dev/myapp")
        assert result == "new-session"
