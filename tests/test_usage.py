"""Tests for claudewatch.backend.services.usage."""

import json
import os
from unittest.mock import patch

from claudewatch.backend.services.usage import MODEL_DISPLAY_NAMES, get_session_model


class TestModelDisplayNames:
    """MODEL_DISPLAY_NAMES mapping tests."""

    def test_known_models_have_display_names(self):
        assert MODEL_DISPLAY_NAMES["claude-opus-4-6"] == "opus 4.6"
        assert MODEL_DISPLAY_NAMES["claude-sonnet-4-6"] == "sonnet 4.6"
        assert MODEL_DISPLAY_NAMES["claude-haiku-4-5"] == "haiku 4.5"


class TestGetSessionModel:
    """Tests for get_session_model."""

    def test_returns_empty_for_missing_project_dir(self, tmp_path):
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_model("/Users/dev/myapp")
        assert result == ""

    def test_returns_empty_for_no_jsonl_files(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_model("/Users/dev/myapp")
        assert result == ""

    def test_returns_display_name_for_known_model(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n")

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_model("/Users/dev/myapp")
        assert result == "opus 4.6"

    def test_returns_raw_model_for_unknown(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-future-99"}}) + "\n")

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_model("/Users/dev/myapp")
        assert result == "claude-future-99"

    def test_uses_last_model_in_file(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-4-6"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n")

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_model("/Users/dev/myapp")
        assert result == "opus 4.6"

    def test_uses_most_recent_jsonl(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)

        old = proj_dir / "old.jsonl"
        with open(old, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-4-6"}}) + "\n")
        os.utime(old, (1000, 1000))

        new = proj_dir / "new.jsonl"
        with open(new, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n")
        os.utime(new, (2000, 2000))

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_model("/Users/dev/myapp")
        assert result == "opus 4.6"

    def test_symlink_traversal_blocked(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        real_jsonl = outside / "evil.jsonl"
        with open(real_jsonl, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n")
        (proj_dir / "session.jsonl").symlink_to(real_jsonl)

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_model("/Users/dev/myapp")
        assert result == ""

    def test_handles_invalid_json_lines(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n")

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_model("/Users/dev/myapp")
        assert result == "opus 4.6"

    def test_handles_non_dict_message(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": "string"}) + "\n")

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_model("/Users/dev/myapp")
        assert result == ""

    def test_returns_empty_for_no_model_field(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n")

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_model("/Users/dev/myapp")
        assert result == ""
