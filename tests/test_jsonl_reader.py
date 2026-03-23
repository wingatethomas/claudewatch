"""Tests for claudewatch.backend.services.jsonl shared reader."""

import os
from unittest.mock import patch

from claudewatch.backend.services.jsonl import (
    find_most_recent_jsonl,
    get_session_id_from_path,
    read_jsonl_full,
    read_jsonl_tail,
)


class TestFindMostRecentJsonl:
    """Tests for find_most_recent_jsonl."""

    def test_returns_none_for_missing_dir(self, tmp_path):
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            assert find_most_recent_jsonl("/Users/dev/myapp") is None

    def test_returns_none_for_empty_dir(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            assert find_most_recent_jsonl("/Users/dev/myapp") is None

    def test_returns_most_recent_jsonl(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)

        old = proj_dir / "old.jsonl"
        old.write_text("{}\n")
        os.utime(old, (1000, 1000))

        new = proj_dir / "new.jsonl"
        new.write_text("{}\n")
        os.utime(new, (2000, 2000))

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = find_most_recent_jsonl("/Users/dev/myapp")
        assert result is not None
        assert result.endswith("new.jsonl")

    def test_blocks_symlink_traversal(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        real_file = outside / "evil.jsonl"
        real_file.write_text("{}\n")
        (proj_dir / "session.jsonl").symlink_to(real_file)

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            assert find_most_recent_jsonl("/Users/dev/myapp") is None

    def test_ignores_non_jsonl_files(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        (proj_dir / "notes.txt").write_text("not jsonl")
        (proj_dir / "session.jsonl").write_text("{}\n")

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = find_most_recent_jsonl("/Users/dev/myapp")
        assert result is not None
        assert result.endswith("session.jsonl")


class TestReadJsonlTail:
    """Tests for read_jsonl_tail."""

    def test_reads_tail_of_file(self, tmp_path):
        f = tmp_path / "test.jsonl"
        content = '{"line": 1}\n' * 100
        f.write_text(content)
        result = read_jsonl_tail(str(f), tail_bytes=50)
        assert len(result) <= 50
        assert "line" in result

    def test_reads_small_file_fully(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"a": 1}\n')
        result = read_jsonl_tail(str(f))
        assert '{"a": 1}' in result

    def test_returns_empty_for_missing_file(self):
        assert read_jsonl_tail("/nonexistent/path.jsonl") == ""


class TestReadJsonlFull:
    """Tests for read_jsonl_full."""

    def test_reads_all_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"a": 1}\n{"b": 2}\n')
        result = read_jsonl_full(str(f))
        assert len(result) == 2

    def test_returns_empty_for_missing_file(self):
        assert read_jsonl_full("/nonexistent/path.jsonl") == []


class TestGetSessionIdFromPath:
    """Tests for get_session_id_from_path."""

    def test_extracts_uuid(self):
        assert get_session_id_from_path("/path/to/abc-123-def.jsonl") == "abc-123-def"

    def test_handles_bare_filename(self):
        assert get_session_id_from_path("session.jsonl") == "session"
