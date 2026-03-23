"""Tests for summarize.py persistent store, cache, and priority queue."""

import json
from unittest.mock import patch

from claudewatch.backend.services import summarize


class TestPersistentStore:
    def setup_method(self) -> None:
        summarize._store = {}
        summarize._store_loaded = False

    def test_load_from_file(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        store_file.write_text(json.dumps({"/test": {"summary": "hello", "mtime": 100.0}}))
        summarize._store_loaded = False
        with patch.object(summarize, "_STORE_PATH", str(store_file)):
            summarize._load_store()
        assert summarize._store["/test"]["summary"] == "hello"

    def test_load_missing_file(self, tmp_path):
        summarize._store_loaded = False
        with patch.object(summarize, "_STORE_PATH", str(tmp_path / "nope.json")):
            summarize._load_store()
        assert summarize._store == {}

    def test_load_corrupt_file(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        store_file.write_text("{corrupt")
        summarize._store_loaded = False
        with patch.object(summarize, "_STORE_PATH", str(store_file)):
            summarize._load_store()
        assert summarize._store == {}

    def test_save_writes_to_disk(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        summarize._store = {"/test": {"summary": "hi", "mtime": 1.0}}
        with patch.object(summarize, "_STORE_PATH", str(store_file)):
            summarize._save_store()
        with open(store_file) as f:
            data = json.load(f)
        assert data["/test"]["summary"] == "hi"

    def test_load_caches(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        store_file.write_text(json.dumps({}))
        summarize._store_loaded = False
        with patch.object(summarize, "_STORE_PATH", str(store_file)):
            summarize._load_store()
            summarize._load_store()  # should not re-read
        assert summarize._store_loaded is True


class TestCacheSummary:
    def setup_method(self) -> None:
        summarize._store = {}
        summarize._store_loaded = True

    def test_cache_and_get(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "s.jsonl"
        jsonl.write_text("{}\n")

        with (
            patch.object(summarize, "_STORE_PATH", str(tmp_path / "store.json")),
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            summarize.cache_summary("/test", "test summary")
            result = summarize.get_cached_summary("/test")
        assert result == "test summary"

    def test_stale_cache_returns_none(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "s.jsonl"
        jsonl.write_text("{}\n")

        summarize._store = {"/test": {"summary": "old", "mtime": 1.0}}
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = summarize.get_cached_summary("/test")
        # mtime of jsonl > cached mtime of 1.0, so stale
        assert result is None


class TestIsGenerating:
    def test_false_when_not_generating(self):
        summarize._in_progress.discard("/test")
        assert summarize.is_generating("/test") is False

    def test_true_when_generating(self):
        summarize._in_progress.add("/test")
        assert summarize.is_generating("/test") is True
        summarize._in_progress.discard("/test")


class TestGetOurPids:
    def test_returns_copy(self):
        summarize._our_pids.add(12345)
        result = summarize.get_our_pids()
        assert 12345 in result
        assert result is not summarize._our_pids
        summarize._our_pids.discard(12345)


class TestPriorityQueue:
    def test_track_adds_to_priority_queue(self, tmp_path):
        summarize._priority_queue.clear()
        summarize._store = {}
        summarize._store_loaded = True
        with (
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")),
            patch.object(summarize, "_ensure_bg_thread"),
        ):
            summarize.track_session("/new-cwd")
        assert "/new-cwd" in summarize._priority_queue
        summarize._priority_queue.clear()

    def test_track_skips_if_cached(self, tmp_path):
        summarize._priority_queue.clear()
        proj_dir = tmp_path / "projects" / "-cached"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "s.jsonl"
        jsonl.write_text("{}\n")

        with (
            patch.object(summarize, "_STORE_PATH", str(tmp_path / "store.json")),
            patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            summarize.cache_summary("/cached", "already done")
            summarize.track_session("/cached")
        assert "/cached" not in summarize._priority_queue
        summarize._priority_queue.clear()

    def test_pending_count(self):
        summarize._priority_queue.clear()
        summarize._priority_queue.extend(["/a", "/b", "/c"])
        assert summarize.pending_summary_count() == 3
        summarize._priority_queue.clear()
