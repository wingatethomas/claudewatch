"""Tests for claudewatch.backend.activity.service."""

import json
import os
from unittest.mock import patch

import pytest

from claudewatch.backend.activity.service import (
    ActivityService,
    _parse_tool_use_dto,
    _truncate,
)
from claudewatch.backend.core.dto import ActivityEventDTO
from claudewatch.backend.core.session_log.service import SessionLogService


def _write_jsonl(path, entries):
    """Write a list of dicts as JSONL lines to a file."""
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestTruncate:
    """Tests for _truncate helper."""

    def test_short_text_unchanged(self):
        assert _truncate("hello", 80) == "hello"

    def test_long_text_truncated_with_ellipsis(self):
        result = _truncate("a" * 100, 80)
        assert len(result) == 80
        assert result.endswith("…")

    def test_newlines_replaced_with_spaces(self):
        assert _truncate("line1\nline2\nline3", 80) == "line1 line2 line3"

    def test_whitespace_stripped(self):
        assert _truncate("  hello  ", 80) == "hello"

    def test_exact_length_not_truncated(self):
        text = "a" * 80
        assert _truncate(text, 80) == text


class TestParseToolUse:
    """Tests for _parse_tool_use_dto helper."""

    def test_bash_command(self):
        block = {"name": "Bash", "input": {"command": "ls -la"}}
        entry = _parse_tool_use_dto(block, "2026-01-01T00:00:00Z")
        assert entry.kind == "tool"
        assert "Bash" in entry.summary
        assert "ls -la" in entry.summary
        assert "ls -la" in entry.detail

    def test_file_path(self):
        block = {"name": "Read", "input": {"file_path": "/Users/dev/project/main.py"}}
        entry = _parse_tool_use_dto(block, "")
        assert "Read" in entry.summary
        assert "main.py" in entry.summary
        assert "/Users/dev/project/main.py" in entry.detail

    def test_pattern(self):
        block = {"name": "Grep", "input": {"pattern": "def.*test"}}
        entry = _parse_tool_use_dto(block, "")
        assert "Grep" in entry.summary
        assert "def.*test" in entry.summary

    def test_unknown_tool(self):
        block = {"name": "CustomTool", "input": {"foo": "bar"}}
        entry = _parse_tool_use_dto(block, "")
        assert entry.summary == "CustomTool"

    def test_missing_name(self):
        block = {"input": {"command": "ls"}}
        entry = _parse_tool_use_dto(block, "")
        assert entry.summary.startswith("Unknown")

    def test_non_dict_input(self):
        block = {"name": "Bash", "input": "string-input"}
        entry = _parse_tool_use_dto(block, "")
        assert entry.summary == "Bash"


class TestParseActivity:
    """Tests for parse_activity."""

    def test_empty_when_no_project_dir(self, tmp_path):
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert result == []

    def test_empty_when_no_jsonl_files(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert result == []

    def test_parses_user_message(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": {"content": "hello world"}, "timestamp": "2026-01-01T00:00:00Z"},
            ],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert len(result) == 1
        assert result[0].kind == "user"
        assert result[0].summary == "hello world"

    def test_parses_assistant_text(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "I'll help you"}]},
                    "timestamp": "2026-01-01T00:00:00Z",
                },
            ],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert len(result) == 1
        assert result[0].kind == "assistant"
        assert "help" in result[0].summary

    def test_parses_tool_use(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}]},
                    "timestamp": "2026-01-01T00:00:00Z",
                },
            ],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert len(result) == 1
        assert result[0].kind == "tool"
        assert "pytest" in result[0].summary

    def test_parses_progress_messages(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {
                    "type": "progress",
                    "data": {
                        "message": {"content": [{"type": "text", "text": "Working on it..."}]},
                    },
                    "timestamp": "2026-01-01T00:00:00Z",
                },
            ],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert len(result) == 1
        assert result[0].kind == "assistant"

    def test_newest_first_ordering(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": {"content": "first"}, "timestamp": "2026-01-01T00:00:00Z"},
                {"type": "user", "message": {"content": "second"}, "timestamp": "2026-01-01T00:01:00Z"},
                {"type": "user", "message": {"content": "third"}, "timestamp": "2026-01-01T00:02:00Z"},
            ],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert len(result) == 3
        assert result[0].detail == "third"
        assert result[2].detail == "first"

    def test_max_entries_cap(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        entries = [
            {"type": "user", "message": {"content": f"msg-{i}"}, "timestamp": f"2026-01-01T00:{i:02d}:00Z"}
            for i in range(10)
        ]
        _write_jsonl(proj_dir / "session.jsonl", entries)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp", max_entries=3)
        assert len(result) == 3
        # Should keep the last 3 (newest)
        assert result[0].detail == "msg-9"

    def test_skips_invalid_json_lines(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps({"type": "user", "message": {"content": "valid"}, "timestamp": ""}) + "\n")
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert len(result) == 1
        assert result[0].detail == "valid"

    def test_skips_empty_user_messages(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": {"content": ""}, "timestamp": ""},
                {"type": "user", "message": {"content": "   "}, "timestamp": ""},
            ],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert result == []

    def test_skips_non_dict_message(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": "string-not-dict", "timestamp": ""},
            ],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert result == []

    def test_symlink_traversal_blocked(self, tmp_path):
        """Symlink pointing outside CLAUDE_PROJECTS_DIR is rejected."""
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        real_jsonl = outside / "evil.jsonl"
        _write_jsonl(
            real_jsonl,
            [
                {"type": "user", "message": {"content": "pwned"}, "timestamp": ""},
            ],
        )
        symlink = proj_dir / "session.jsonl"
        symlink.symlink_to(real_jsonl)

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert result == []

    def test_uses_most_recent_jsonl(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        old = proj_dir / "old.jsonl"
        _write_jsonl(
            old,
            [
                {"type": "user", "message": {"content": "old msg"}, "timestamp": ""},
            ],
        )
        os.utime(old, (1000, 1000))

        new = proj_dir / "new.jsonl"
        _write_jsonl(
            new,
            [
                {"type": "user", "message": {"content": "new msg"}, "timestamp": ""},
            ],
        )
        os.utime(new, (2000, 2000))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert len(result) == 1
        assert result[0].detail == "new msg"

    def test_session_id_reads_that_sessions_file_not_newest_sibling(self, tmp_path):
        """Two sessions share a cwd; parse(cwd, old_sid) must not read the newer sibling."""
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        sid_old = "11111111-1111-1111-1111-111111111111"
        sid_new = "22222222-2222-2222-2222-222222222222"
        old = proj_dir / f"{sid_old}.jsonl"
        _write_jsonl(old, [{"type": "user", "message": {"content": "old msg"}, "timestamp": ""}])
        os.utime(old, (1000, 1000))
        new = proj_dir / f"{sid_new}.jsonl"
        _write_jsonl(new, [{"type": "user", "message": {"content": "new msg"}, "timestamp": ""}])
        os.utime(new, (2000, 2000))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp", sid_old)
        assert len(result) == 1
        assert result[0].detail == "old msg"

    def test_session_id_missing_file_returns_empty_no_sibling_fallback(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "22222222-2222-2222-2222-222222222222.jsonl",
            [{"type": "user", "message": {"content": "sibling msg"}, "timestamp": ""}],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse(
                "/Users/dev/myapp", "11111111-1111-1111-1111-111111111111"
            )
        assert result == []

    def test_empty_session_id_falls_back_to_most_recent(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        old = proj_dir / "old.jsonl"
        _write_jsonl(old, [{"type": "user", "message": {"content": "old msg"}, "timestamp": ""}])
        os.utime(old, (1000, 1000))
        new = proj_dir / "new.jsonl"
        _write_jsonl(new, [{"type": "user", "message": {"content": "new msg"}, "timestamp": ""}])
        os.utime(new, (2000, 2000))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp", "")
        assert len(result) == 1
        assert result[0].detail == "new msg"

    def test_parses_recap_from_away_summary(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": {"content": "fix auth"}, "timestamp": "2026-01-01T00:00:00Z"},
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Fixed auth middleware and added tests.",
                    "timestamp": "2026-01-01T00:05:00Z",
                },
            ],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        recaps = [e for e in result if e.kind == "recap"]
        assert len(recaps) == 1
        assert recaps[0].detail == "Fixed auth middleware and added tests."

    def test_ignores_non_recap_system_entries(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "system", "subtype": "other", "content": "not a recap", "timestamp": ""},
            ],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert result == []

    def test_skips_non_list_assistant_content(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "assistant", "message": {"content": "string-not-list"}, "timestamp": ""},
            ],
        )
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = ActivityService(SessionLogService()).parse("/Users/dev/myapp")
        assert result == []


class TestActivityService:
    """Tests for ActivityService.parse() returning ActivityEventDTO."""

    def _make_service(self) -> ActivityService:
        return ActivityService(SessionLogService())

    def test_returns_activity_event_dtos(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": {"content": "hello"}, "timestamp": "2026-01-01T00:00:00Z"},
            ],
        )
        svc = self._make_service()
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.parse("/Users/dev/myapp")
        assert len(result) == 1
        assert isinstance(result[0], ActivityEventDTO)
        assert result[0].kind == "user"
        assert result[0].summary == "hello"

    def test_empty_when_no_jsonl(self, tmp_path):
        svc = self._make_service()
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.parse("/Users/dev/myapp")
        assert result == []

    def test_parses_tool_use_dto(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}]},
                    "timestamp": "2026-01-01T00:00:00Z",
                },
            ],
        )
        svc = self._make_service()
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.parse("/Users/dev/myapp")
        assert len(result) == 1
        assert isinstance(result[0], ActivityEventDTO)
        assert result[0].kind == "tool"
        assert "pytest" in result[0].summary

    def test_max_entries_cap(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        entries = [
            {"type": "user", "message": {"content": f"msg-{i}"}, "timestamp": f"2026-01-01T00:{i:02d}:00Z"}
            for i in range(10)
        ]
        _write_jsonl(proj_dir / "session.jsonl", entries)
        svc = self._make_service()
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.parse("/Users/dev/myapp", max_entries=3)
        assert len(result) == 3
        assert result[0].detail == "msg-9"

    def test_newest_first_ordering(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": {"content": "first"}, "timestamp": "2026-01-01T00:00:00Z"},
                {"type": "user", "message": {"content": "second"}, "timestamp": "2026-01-01T00:01:00Z"},
            ],
        )
        svc = self._make_service()
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.parse("/Users/dev/myapp")
        assert result[0].detail == "second"
        assert result[1].detail == "first"

    def test_dto_is_frozen(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": {"content": "hello"}, "timestamp": ""},
            ],
        )
        svc = self._make_service()
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.parse("/Users/dev/myapp")

        with pytest.raises(AttributeError):
            result[0].kind = "changed"
