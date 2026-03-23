"""Tests for claudewatch.backend.services.summarize."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from claudewatch.backend.services.summarize import (
    _call_claude,
    _extract_conversation_text,
)


def _write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestExtractConversationText:
    """Tests for _extract_conversation_text."""

    def test_extracts_user_messages(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "fix the login bug"}, "timestamp": ""}],
        )
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _extract_conversation_text("/Users/dev/myapp")
        assert "User: fix the login bug" in result

    def test_extracts_assistant_text(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "I'll help you fix that"}]},
                    "timestamp": "",
                },
            ],
        )
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _extract_conversation_text("/Users/dev/myapp")
        assert "Assistant: I'll help you fix that" in result

    def test_respects_max_context_chars(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        entries = [{"type": "user", "message": {"content": "x" * 2000}, "timestamp": ""} for _ in range(10)]
        _write_jsonl(proj_dir / "session.jsonl", entries)
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _extract_conversation_text("/Users/dev/myapp")
        assert len(result) <= 25000  # 8000 char limit + "User: " prefixes

    def test_returns_empty_for_missing_project(self, tmp_path):
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            result = _extract_conversation_text("/Users/dev/myapp")
        assert result == ""

    def test_skips_invalid_json(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"type": "user", "message": {"content": "valid"}, "timestamp": ""}) + "\n")
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _extract_conversation_text("/Users/dev/myapp")
        assert "valid" in result

    def test_skips_non_dict_messages(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": "string-not-dict", "timestamp": ""}],
        )
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = _extract_conversation_text("/Users/dev/myapp")
        assert result == ""


class TestGenerateSummary:
    """Tests for _call_claude."""

    def test_returns_empty_when_claude_not_found(self, tmp_path):
        with patch("claudewatch.backend.services.summarize.shutil.which", return_value=None):
            result = _call_claude("/Users/dev/myapp")
        assert result == ""

    def test_returns_empty_when_no_conversation(self, tmp_path):
        with (
            patch("claudewatch.backend.services.summarize.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")),
        ):
            result = _call_claude("/Users/dev/myapp")
        assert result == ""

    def test_returns_summary_on_success(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "fix auth"}, "timestamp": ""}],
        )
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.communicate.return_value = ("Fixed auth middleware\n", "")
        mock_proc.returncode = 0
        with (
            patch("claudewatch.backend.services.summarize.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.services.summarize.subprocess.Popen", return_value=mock_proc),
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            result = _call_claude("/Users/dev/myapp")
        assert result == "Fixed auth middleware"

    def test_returns_empty_on_timeout(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "fix auth"}, "timestamp": ""}],
        )
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired("claude", 15)
        with (
            patch("claudewatch.backend.services.summarize.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.services.summarize.subprocess.Popen", return_value=mock_proc),
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            result = _call_claude("/Users/dev/myapp")
        assert result == ""

    def test_returns_empty_on_nonzero_exit(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "fix auth"}, "timestamp": ""}],
        )
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 1
        with (
            patch("claudewatch.backend.services.summarize.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.services.summarize.subprocess.Popen", return_value=mock_proc),
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            result = _call_claude("/Users/dev/myapp")
        assert result == ""
