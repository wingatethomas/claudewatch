"""Tests for claudewatch.backend.services.usage."""

import json
import os
from unittest.mock import MagicMock, patch

from claudewatch.backend.services.usage import MODEL_DISPLAY_NAMES, UsageService, get_session_model


def _make_svc(
    find_most_recent: str | None = None,
    read_tail: str = "",
    read_full: list[str] | None = None,
) -> UsageService:
    """Create a UsageService with a mocked SessionLogService."""
    mock_log = MagicMock()
    mock_log.find_most_recent.return_value = find_most_recent
    mock_log.read_tail.return_value = read_tail
    mock_log.read_full.return_value = read_full or []
    return UsageService(mock_log)


class TestModelDisplayNames:
    """MODEL_DISPLAY_NAMES mapping tests."""

    def test_known_models_have_display_names(self):
        assert MODEL_DISPLAY_NAMES["claude-opus-4-6"] == "opus 4.6"
        assert MODEL_DISPLAY_NAMES["claude-sonnet-4-6"] == "sonnet 4.6"
        assert MODEL_DISPLAY_NAMES["claude-haiku-4-5"] == "haiku 4.5"


class TestUsageServiceGetModel:
    """Tests for UsageService.get_model."""

    def test_returns_empty_when_no_jsonl_found(self):
        svc = _make_svc(find_most_recent=None)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_empty_when_tail_empty(self):
        svc = _make_svc(find_most_recent="/fake/path.jsonl", read_tail="")
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_display_name_for_known_model(self):
        tail = json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n"
        svc = _make_svc(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "opus 4.6"

    def test_returns_raw_model_for_unknown(self):
        tail = json.dumps({"type": "assistant", "message": {"model": "claude-future-99"}}) + "\n"
        svc = _make_svc(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-future-99"

    def test_uses_last_model_in_file(self):
        tail = (
            json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-4-6"}}) + "\n"
            + json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n"
        )
        svc = _make_svc(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "opus 4.6"

    def test_handles_invalid_json_lines(self):
        tail = (
            "not json\n"
            + json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n"
        )
        svc = _make_svc(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "opus 4.6"

    def test_handles_non_dict_message(self):
        tail = json.dumps({"type": "assistant", "message": "string"}) + "\n"
        svc = _make_svc(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_empty_for_no_model_field(self):
        tail = json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n"
        svc = _make_svc(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == ""


class TestGetSessionModel:
    """Tests for legacy get_session_model function."""

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
