"""Tests for claudewatch.backend.services.summarize."""

import json
import subprocess
from unittest.mock import patch

from claudewatch.backend.services.summarize import (
    _extract_conversation_text,
    generate_summary,
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
    """Tests for generate_summary."""

    def test_returns_empty_when_claude_not_found(self, tmp_path):
        with patch("claudewatch.backend.services.summarize.shutil.which", return_value=None):
            result = generate_summary("/Users/dev/myapp")
        assert result == ""

    def test_returns_empty_when_no_conversation(self, tmp_path):
        with (
            patch("claudewatch.backend.services.summarize.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")),
        ):
            result = generate_summary("/Users/dev/myapp")
        assert result == ""

    def test_returns_summary_on_success(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "fix auth"}, "timestamp": ""}],
        )
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="Fixed auth middleware\n")
        with (
            patch("claudewatch.backend.services.summarize.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.services.summarize.subprocess.run", return_value=mock_result),
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            result = generate_summary("/Users/dev/myapp")
        assert result == "Fixed auth middleware"

    def test_returns_empty_on_timeout(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "fix auth"}, "timestamp": ""}],
        )
        with (
            patch("claudewatch.backend.services.summarize.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "claudewatch.backend.services.summarize.subprocess.run",
                side_effect=subprocess.TimeoutExpired("claude", 15),
            ),
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            result = generate_summary("/Users/dev/myapp")
        assert result == ""

    def test_returns_empty_on_nonzero_exit(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "fix auth"}, "timestamp": ""}],
        )
        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with (
            patch("claudewatch.backend.services.summarize.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.services.summarize.subprocess.run", return_value=mock_result),
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            result = generate_summary("/Users/dev/myapp")
        assert result == ""
