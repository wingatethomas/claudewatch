"""Tests for claudewatch.backend.core.session_log.jsonl shared reader."""

import os
from unittest.mock import patch

from claudewatch.backend.core.session_log.jsonl import (
    find_most_recent_jsonl,
    get_session_id_from_path,
    list_jsonls_in_cwd,
    read_ai_title,
    read_ai_title_full,
    read_jsonl_full,
    read_jsonl_tail,
)


class TestFindMostRecentJsonl:
    """Tests for find_most_recent_jsonl."""

    def test_returns_none_for_missing_dir(self, tmp_path):
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            assert find_most_recent_jsonl("/Users/dev/myapp") is None

    def test_returns_none_for_empty_dir(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
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

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
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

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            assert find_most_recent_jsonl("/Users/dev/myapp") is None

    def test_ignores_non_jsonl_files(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        (proj_dir / "notes.txt").write_text("not jsonl")
        (proj_dir / "session.jsonl").write_text("{}\n")

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
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

    def test_refuses_symlink_at_final_component(self, tmp_path):
        """O_NOFOLLOW: a symlink at the final path component must not be followed."""
        target = tmp_path / "real.jsonl"
        target.write_text('{"a": 1}\n')
        link = tmp_path / "linked.jsonl"
        link.symlink_to(target)
        # Direct read of the real file works.
        assert '{"a": 1}' in read_jsonl_tail(str(target))
        # Read through the symlink is refused (returns "").
        assert read_jsonl_tail(str(link)) == ""


class TestReadJsonlFull:
    """Tests for read_jsonl_full."""

    def test_reads_all_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"a": 1}\n{"b": 2}\n')
        result = read_jsonl_full(str(f))
        assert len(result) == 2

    def test_returns_empty_for_missing_file(self):
        assert read_jsonl_full("/nonexistent/path.jsonl") == []

    def test_refuses_symlink_at_final_component(self, tmp_path):
        """O_NOFOLLOW: symlink at the final path component must not be followed."""
        target = tmp_path / "real.jsonl"
        target.write_text('{"x": 1}\n')
        link = tmp_path / "linked.jsonl"
        link.symlink_to(target)
        assert read_jsonl_full(str(target)) == ['{"x": 1}\n']
        assert read_jsonl_full(str(link)) == []


class TestGetSessionIdFromPath:
    """Tests for get_session_id_from_path."""

    def test_extracts_uuid(self):
        assert get_session_id_from_path("/path/to/abc-123-def.jsonl") == "abc-123-def"

    def test_handles_bare_filename(self):
        assert get_session_id_from_path("session.jsonl") == "session"


class TestListJsonlsInCwd:
    """Tests for list_jsonls_in_cwd."""

    def test_returns_empty_for_missing_dir(self, tmp_path):
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            assert list_jsonls_in_cwd("/Users/dev/myapp") == []

    def test_returns_mtime_descending(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        old = proj_dir / "old.jsonl"
        old.write_text("{}\n")
        os.utime(old, (1000, 1000))
        new = proj_dir / "new.jsonl"
        new.write_text("{}\n")
        os.utime(new, (2000, 2000))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = list_jsonls_in_cwd("/Users/dev/myapp")
        assert [os.path.basename(p) for p in result] == ["new.jsonl", "old.jsonl"]

    def test_filters_symlink_traversal(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        evil = outside / "evil.jsonl"
        evil.write_text("{}\n")
        (proj_dir / "linked.jsonl").symlink_to(evil)
        safe = proj_dir / "safe.jsonl"
        safe.write_text("{}\n")

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = list_jsonls_in_cwd("/Users/dev/myapp")
        assert [os.path.basename(p) for p in result] == ["safe.jsonl"]


class TestReadAiTitle:
    """Tests for read_ai_title."""

    def test_returns_empty_when_no_ai_title(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text('{"type": "assistant", "message": {"content": []}}\n')
        assert read_ai_title(str(f)) == ""

    def test_returns_ai_title(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text('{"type": "ai-title", "aiTitle": "Fix detection logic"}\n')
        assert read_ai_title(str(f)) == "Fix detection logic"

    def test_returns_latest_when_multiple(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text(
            '{"type": "ai-title", "aiTitle": "First title"}\n'
            '{"type": "assistant", "message": {"content": []}}\n'
            '{"type": "ai-title", "aiTitle": "Updated title"}\n'
        )
        assert read_ai_title(str(f)) == "Updated title"

    def test_returns_empty_for_missing_file(self):
        assert read_ai_title("/nonexistent/x.jsonl") == ""

    def test_skips_malformed_json(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text('not-json-at-all\n{"type": "ai-title", "aiTitle": "Valid title"}\n')
        assert read_ai_title(str(f)) == "Valid title"


class TestReadAiTitleFull:
    """Tests for read_ai_title_full."""

    def _long_session(self, tmp_path, title_line: str):
        filler = '{"type": "assistant", "message": {"content": [{"type": "text", "text": "%s"}]}}\n' % ("x" * 200)
        f = tmp_path / "s.jsonl"
        f.write_text(title_line + filler * 100)
        return f

    def test_finds_title_outside_tail_window(self, tmp_path):
        f = self._long_session(tmp_path, '{"type": "ai-title", "aiTitle": "Old long session"}\n')
        assert read_ai_title(str(f)) == ""
        assert read_ai_title_full(str(f)) == "Old long session"

    def test_returns_latest_when_multiple(self, tmp_path):
        f = tmp_path / "s.jsonl"
        f.write_text('{"type": "ai-title", "aiTitle": "First"}\n{"type": "ai-title", "aiTitle": "Second"}\n')
        assert read_ai_title_full(str(f)) == "Second"

    def test_returns_empty_when_no_title(self, tmp_path):
        f = self._long_session(tmp_path, "")
        assert read_ai_title_full(str(f)) == ""

    def test_returns_empty_for_missing_file(self):
        assert read_ai_title_full("/nonexistent/x.jsonl") == ""
