"""Tests for SummaryRepository — persistent store I/O and staleness checks."""

import json
import time

from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.summary.models import SummaryEntry
from claudewatch.backend.summary.repository import SummaryRepository


def _make_repo(tmp_path, store_name="summaries.json"):
    store_path = str(tmp_path / store_name)
    return SummaryRepository(SessionLogService(), store_path=store_path)


class TestLoadStore:
    def test_load_from_file(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        store_file.write_text(json.dumps({"/test": {"summary": "hello", "mtime": time.time()}}))
        repo = _make_repo(tmp_path)
        repo.load_store()
        assert repo._store["/test"].summary == "hello"

    def test_load_missing_file(self, tmp_path):
        repo = _make_repo(tmp_path, "nope.json")
        repo.load_store()
        assert repo._store == {}

    def test_load_corrupt_file(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        store_file.write_text("{corrupt")
        repo = _make_repo(tmp_path)
        repo.load_store()
        assert repo._store == {}

    def test_load_caches(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        store_file.write_text(json.dumps({}))
        repo = _make_repo(tmp_path)
        repo.load_store()
        repo.load_store()  # should not re-read
        assert repo._store_loaded is True


class TestSaveStore:
    def test_save_writes_to_disk(self, tmp_path):
        repo = _make_repo(tmp_path)
        repo._store = {"/test": SummaryEntry(title="", summary="hi", mtime=1.0)}
        repo._save_store()
        with open(tmp_path / "summaries.json") as f:
            data = json.load(f)
        assert data["/test"]["summary"] == "hi"


class TestGetEntry:
    def test_returns_entry_when_fresh(self, tmp_path):
        from unittest.mock import patch

        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        repo = _make_repo(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            repo.cache("/test", "test summary")
            entry = repo.get_entry("/test")
        assert entry is not None
        assert entry.title == "test summary"

    def test_returns_none_when_no_jsonl(self, tmp_path):
        repo = _make_repo(tmp_path)
        repo._store_loaded = True
        repo._store = {"/test": SummaryEntry(title="old", summary="", mtime=1.0)}
        entry = repo.get_entry("/test")
        assert entry is None


class TestCache:
    def test_cache_and_get(self, tmp_path):
        from unittest.mock import patch

        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        repo = _make_repo(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            repo.cache("/test", "test summary")
            entry = repo.get_entry("/test")
        assert entry is not None
        assert entry.title == "test summary"

    def test_cache_with_session_id(self, tmp_path):
        from unittest.mock import patch

        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "session-1.jsonl").write_text("{}\n")
        (proj_dir / "session-2.jsonl").write_text("{}\n")

        repo = _make_repo(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            repo.cache("/test", "summary A", "session-1")
            repo.cache("/test", "summary B", "session-2")
            a = repo.get_entry("/test", "session-1")
            b = repo.get_entry("/test", "session-2")
        assert a is not None
        assert a.title == "summary A"
        assert b is not None
        assert b.title == "summary B"

    def test_sibling_activity_does_not_invalidate_entry(self, tmp_path):
        """A sibling session's fresh JSONL must not stale this session's entry."""
        from unittest.mock import patch

        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "mine.jsonl").write_text("{}\n")

        repo = _make_repo(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            repo.cache_full("/test", "title", "recap", "mine")
            (proj_dir / "sibling.jsonl").write_text("{}\n" * 5000)
            entry = repo.get_entry("/test", "mine")
        assert entry is not None
        assert entry.summary == "recap"

    def test_entry_recorded_from_larger_file_invalidates(self, tmp_path):
        """An entry whose recorded size exceeds the file was cached from a
        sibling's JSONL (files only append) — it must not be served."""
        from unittest.mock import patch

        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "mine.jsonl").write_text("{}\n")

        repo = _make_repo(tmp_path)
        repo._store_loaded = True
        repo._store = {
            "/test::mine": SummaryEntry(title="wrong", summary="sibling recap", mtime=time.time(), jsonl_size=2824980)
        }
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            assert repo.get_entry("/test", "mine") is None

    def test_own_file_growth_invalidates_entry(self, tmp_path):
        from unittest.mock import patch

        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "mine.jsonl").write_text("{}\n")

        repo = _make_repo(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            repo.cache_full("/test", "title", "recap", "mine")
            (proj_dir / "mine.jsonl").write_text("x" * 20480)  # grew past the 10KB threshold
            entry = repo.get_entry("/test", "mine")
        assert entry is None


class TestClearAll:
    def test_clears_all_entries(self, tmp_path):
        repo = _make_repo(tmp_path)
        repo._store_loaded = True
        repo._store = {"/a": SummaryEntry(title="a", summary="", mtime=1.0)}
        repo.clear_all()
        assert repo._store == {}


class TestInvalidateEntry:
    def test_removes_single_entry(self, tmp_path):
        repo = _make_repo(tmp_path)
        repo._store_loaded = True
        repo._store = {
            "/a": SummaryEntry(title="a", summary="", mtime=1.0),
            "/b": SummaryEntry(title="b", summary="", mtime=1.0),
        }
        repo.invalidate_entry("/a")
        assert "/a" not in repo._store
        assert "/b" in repo._store
