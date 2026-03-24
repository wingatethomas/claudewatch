"""Tests for claudewatch.backend.summary.service.SummaryService."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from claudewatch.backend.core.process.service import ProcessService
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.summary.service import SummaryService


def _make_service(tmp_path, projects_dir=None):
    """Create a SummaryService wired to tmp_path fixtures."""
    session_log_service = SessionLogService()
    process_service = ProcessService()
    store_path = str(tmp_path / "summaries.json")
    return SummaryService(session_log_service, process_service, store_path=store_path), projects_dir


def _write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestExtractConversationText:
    """Tests for SummaryService._extract_conversation_text."""

    def test_extracts_user_messages(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "fix the login bug"}, "timestamp": ""}],
        )
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_conversation_text("/Users/dev/myapp")
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
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_conversation_text("/Users/dev/myapp")
        assert "Assistant: I'll help you fix that" in result

    def test_respects_max_context_chars(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        entries = [{"type": "user", "message": {"content": "x" * 2000}, "timestamp": ""} for _ in range(10)]
        _write_jsonl(proj_dir / "session.jsonl", entries)
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_conversation_text("/Users/dev/myapp")
        assert len(result) <= 25000

    def test_returns_empty_for_missing_project(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            result = svc._extract_conversation_text("/Users/dev/myapp")
        assert result == ""

    def test_skips_invalid_json(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl_file = proj_dir / "session.jsonl"
        with open(jsonl_file, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"type": "user", "message": {"content": "valid"}, "timestamp": ""}) + "\n")
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_conversation_text("/Users/dev/myapp")
        assert "valid" in result

    def test_skips_non_dict_messages(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": "string-not-dict", "timestamp": ""}],
        )
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_conversation_text("/Users/dev/myapp")
        assert result == ""


class TestCallClaude:
    """Tests for SummaryService._call_claude."""

    def test_returns_empty_when_claude_not_found(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.summary.service.shutil.which", return_value=None):
            result = svc._call_claude("/Users/dev/myapp")
        assert result == ""

    def test_returns_empty_when_no_conversation(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.summary.service.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")),
        ):
            result = svc._call_claude("/Users/dev/myapp")
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
        svc, _ = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.summary.service.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.summary.service.subprocess.Popen", return_value=mock_proc),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            result = svc._call_claude("/Users/dev/myapp")
        assert result == "Fixed auth middleware"

    def test_registers_and_unregisters_child_pid(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "fix auth"}, "timestamp": ""}],
        )
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.communicate.return_value = ("summary\n", "")
        mock_proc.returncode = 0
        svc, _ = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.summary.service.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.summary.service.subprocess.Popen", return_value=mock_proc),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            svc._call_claude("/Users/dev/myapp")
        # After call, PID should be unregistered
        assert 99999 not in svc._process_service.get_child_pids()

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
        svc, _ = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.summary.service.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.summary.service.subprocess.Popen", return_value=mock_proc),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            result = svc._call_claude("/Users/dev/myapp")
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
        svc, _ = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.summary.service.shutil.which", return_value="/usr/bin/claude"),
            patch("claudewatch.backend.summary.service.subprocess.Popen", return_value=mock_proc),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            result = svc._call_claude("/Users/dev/myapp")
        assert result == ""


class TestPersistentStore:
    def test_load_from_file(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        store_file.write_text(json.dumps({"/test": {"summary": "hello", "mtime": 100.0}}))
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(store_file))
        svc._load_store()
        assert svc._store["/test"]["summary"] == "hello"

    def test_load_missing_file(self, tmp_path):
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(tmp_path / "nope.json"))
        svc._load_store()
        assert svc._store == {}

    def test_load_corrupt_file(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        store_file.write_text("{corrupt")
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(store_file))
        svc._load_store()
        assert svc._store == {}

    def test_save_writes_to_disk(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(store_file))
        svc._store = {"/test": {"summary": "hi", "mtime": 1.0}}
        svc._save_store()
        with open(store_file) as f:
            data = json.load(f)
        assert data["/test"]["summary"] == "hi"

    def test_load_caches(self, tmp_path):
        store_file = tmp_path / "summaries.json"
        store_file.write_text(json.dumps({}))
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(store_file))
        svc._load_store()
        svc._load_store()  # should not re-read
        assert svc._store_loaded is True


class TestCacheSummary:
    def test_cache_and_get(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        jsonl_file = proj_dir / "s.jsonl"
        jsonl_file.write_text("{}\n")

        store_file = tmp_path / "store.json"
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(store_file))
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            svc.cache("/test", "test summary")
            result = svc.get_cached("/test")
        assert result == "test summary"

    def test_stale_cache_returns_none(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        jsonl_file = proj_dir / "s.jsonl"
        jsonl_file.write_text("{}\n")

        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(tmp_path / "store.json"))
        svc._store_loaded = True
        svc._store = {"/test": {"summary": "old", "mtime": 1.0}}
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.get_cached("/test")
        # mtime of jsonl > cached mtime of 1.0, so stale
        assert result is None


class TestIsGenerating:
    def test_false_when_not_generating(self, tmp_path):
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(tmp_path / "s.json"))
        assert svc.is_generating("/test") is False

    def test_true_when_generating(self, tmp_path):
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(tmp_path / "s.json"))
        svc._in_progress.add("/test")
        assert svc.is_generating("/test") is True


class TestPriorityQueue:
    def test_track_adds_to_priority_queue(self, tmp_path):
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(tmp_path / "s.json"))
        svc._store_loaded = True
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")),
            patch.object(svc, "_ensure_bg_thread"),
        ):
            svc.track_session("/new-cwd")
        assert "/new-cwd" in svc._priority_queue

    def test_track_skips_if_cached(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-cached"
        proj_dir.mkdir(parents=True)
        jsonl_file = proj_dir / "s.jsonl"
        jsonl_file.write_text("{}\n")

        store_file = tmp_path / "store.json"
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(store_file))
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch.object(svc, "_ensure_bg_thread"),
        ):
            svc.cache("/cached", "already done")
            svc.track_session("/cached")
        assert "/cached" not in svc._priority_queue

    def test_pending_count(self, tmp_path):
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(tmp_path / "s.json"))
        svc._priority_queue.extend(["/a", "/b", "/c"])
        assert svc.pending_summary_count() == 3


class TestInvalidateCache:
    def test_invalidate_removes_entry(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        store_file = tmp_path / "store.json"
        svc = SummaryService(SessionLogService(), ProcessService(), store_path=str(store_file))
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            svc.cache("/test", "summary")
            assert svc.get_cached("/test") == "summary"
            svc.invalidate_cache("/test")
            assert svc.get_cached("/test") is None
