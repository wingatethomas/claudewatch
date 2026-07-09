"""Tests for claudewatch.backend.summary.service.SummaryService."""

import json
import os
from unittest.mock import patch

from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.summary.models import SummaryEntry
from claudewatch.backend.summary.service import (
    SummaryService,
    _find_last_ai_title,
    _find_last_recap,
    _truncate_title,
)


def _make_service(tmp_path):
    """Create a SummaryService wired to tmp_path fixtures."""
    from claudewatch.backend.summary.repository import SummaryRepository

    session_log_service = SessionLogService()
    store_path = str(tmp_path / "summaries.json")
    repo = SummaryRepository(session_log_service, store_path=store_path)
    return SummaryService(repo, session_log_service)


def _write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestTruncateTitle:
    def test_short_title_unchanged(self) -> None:
        assert _truncate_title("Short") == "Short"

    def test_long_title_truncated_at_word_boundary(self) -> None:
        result = _truncate_title("This is a very long title that should be truncated")
        assert len(result) <= 30
        assert not result.endswith(" ")

    def test_title_at_exact_limit(self) -> None:
        title = "A" * 30
        assert _truncate_title(title) == title


class TestFindLastRecap:
    def test_returns_recap_content(self) -> None:
        lines = [
            json.dumps({"type": "user", "message": {"content": "hi"}}),
            json.dumps({"type": "system", "subtype": "away_summary", "content": "Did stuff."}),
        ]
        assert _find_last_recap(lines) == "Did stuff."

    def test_returns_most_recent_when_multiple(self) -> None:
        lines = [
            json.dumps({"type": "system", "subtype": "away_summary", "content": "Old."}),
            json.dumps({"type": "system", "subtype": "away_summary", "content": "New."}),
        ]
        assert _find_last_recap(lines) == "New."

    def test_skips_empty_content(self) -> None:
        lines = [
            json.dumps({"type": "system", "subtype": "away_summary", "content": ""}),
        ]
        assert _find_last_recap(lines) is None

    def test_skips_other_subtypes(self) -> None:
        lines = [json.dumps({"type": "system", "subtype": "other", "content": "x"})]
        assert _find_last_recap(lines) is None

    def test_skips_invalid_json(self) -> None:
        lines = [
            "not json",
            json.dumps({"type": "system", "subtype": "away_summary", "content": "ok"}),
        ]
        assert _find_last_recap(lines) == "ok"


class TestFindLastAiTitle:
    def test_returns_ai_title(self) -> None:
        lines = [json.dumps({"type": "ai-title", "aiTitle": "Refactor auth module"})]
        assert _find_last_ai_title(lines) == "Refactor auth module"

    def test_returns_most_recent(self) -> None:
        lines = [
            json.dumps({"type": "ai-title", "aiTitle": "First"}),
            json.dumps({"type": "ai-title", "aiTitle": "Second"}),
        ]
        assert _find_last_ai_title(lines) == "Second"

    def test_returns_none_when_absent(self) -> None:
        lines = [json.dumps({"type": "user", "message": {"content": "hi"}})]
        assert _find_last_ai_title(lines) is None

    def test_skips_empty_ai_title(self) -> None:
        lines = [json.dumps({"type": "ai-title", "aiTitle": "  "})]
        assert _find_last_ai_title(lines) is None


class TestExtractRecap:
    """Tests for SummaryService._extract_recap."""

    def test_returns_recap_from_away_summary(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": {"content": "fix auth"}, "timestamp": ""},
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Fixed auth middleware and added tests.",
                    "timestamp": "2026-01-01T00:05:00Z",
                },
            ],
        )
        svc = _make_service(tmp_path)
        result = svc._extract_recap(str(proj_dir / "session.jsonl"))
        assert result == "Fixed auth middleware and added tests."

    def test_returns_none_when_no_recap(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "hello"}, "timestamp": ""}],
        )
        svc = _make_service(tmp_path)
        result = svc._extract_recap(str(proj_dir / "session.jsonl"))
        assert result is None

    def test_returns_none_for_missing_file(self, tmp_path):
        svc = _make_service(tmp_path)
        result = svc._extract_recap(str(tmp_path / "nope.jsonl"))
        assert result is None

    def test_full_scan_finds_recap_past_tail(self, tmp_path):
        """Recap deep in a large file is found via the full-scan fallback."""
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        entries = [
            {
                "type": "system",
                "subtype": "away_summary",
                "content": "Early recap deep in the file.",
                "timestamp": "2026-01-01T00:00:00Z",
            },
        ]
        filler = {"type": "user", "message": {"content": "x" * 500}, "timestamp": ""}
        entries.extend([filler] * 500)
        _write_jsonl(proj_dir / "session.jsonl", entries)

        svc = _make_service(tmp_path)
        result = svc._extract_recap(str(proj_dir / "session.jsonl"))
        assert result == "Early recap deep in the file."


class TestExtractAiTitle:
    """Tests for SummaryService._extract_ai_title."""

    def test_returns_ai_title_when_present(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "ai-title", "aiTitle": "Refactor auth module", "sessionId": "abc"},
                {"type": "user", "message": {"content": "fix auth"}, "timestamp": ""},
            ],
        )
        svc = _make_service(tmp_path)
        result = svc._extract_ai_title(str(proj_dir / "session.jsonl"))
        assert result == "Refactor auth module"

    def test_returns_none_when_absent(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "hi"}, "timestamp": ""}],
        )
        svc = _make_service(tmp_path)
        result = svc._extract_ai_title(str(proj_dir / "session.jsonl"))
        assert result is None


class TestGenerateAndCache:
    """Tests for SummaryService.generate_and_cache."""

    def test_caches_recap_when_present(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": {"content": "fix auth"}, "timestamp": ""},
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Fixed auth middleware and added integration tests.",
                    "timestamp": "2026-01-01T00:05:00Z",
                },
            ],
        )
        svc = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.generate_and_cache("/Users/dev/myapp")
            assert result
            cached = svc.get_cached_summary("/Users/dev/myapp")
            assert cached == "Fixed auth middleware and added integration tests."

    def test_shared_cwd_sessions_get_their_own_recaps(self, tmp_path):
        """Each session reads its own JSONL — never a sibling's recap."""
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "sess-a.jsonl",
            [
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Recap for session A.",
                    "timestamp": "2026-01-01T00:05:00Z",
                },
            ],
        )
        _write_jsonl(
            proj_dir / "sess-b.jsonl",
            [
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Recap for session B.",
                    "timestamp": "2026-01-01T00:06:00Z",
                },
            ],
        )
        svc = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            svc.generate_and_cache("/Users/dev/myapp", "sess-a")
            svc.generate_and_cache("/Users/dev/myapp", "sess-b")
            assert svc.get_cached_summary("/Users/dev/myapp", "sess-a") == "Recap for session A."
            assert svc.get_cached_summary("/Users/dev/myapp", "sess-b") == "Recap for session B."

    def test_missing_session_file_yields_no_summary(self, tmp_path):
        """A session_id whose JSONL is gone must not fall back to a sibling's file."""
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "other.jsonl",
            [
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Sibling recap.",
                    "timestamp": "2026-01-01T00:05:00Z",
                },
            ],
        )
        svc = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            assert svc.generate_and_cache("/Users/dev/myapp", "gone") == ""
            assert svc.get_cached_summary("/Users/dev/myapp", "gone") is None

    def test_caches_title_alone_when_no_recap_yet(self, tmp_path):
        """Sessions without a recap still get their aiTitle cached for display."""
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "ai-title", "aiTitle": "Refactor auth module"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
            ],
        )
        svc = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            title = svc.generate_and_cache("/Users/dev/myapp")
            assert title == "Refactor auth module"
            assert svc.get_cached("/Users/dev/myapp") == "Refactor auth module"
            # No recap content — the Summary submenu still shows its placeholder.
            assert not svc.get_cached_summary("/Users/dev/myapp")

    def test_uses_ai_title_when_available(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "ai-title", "aiTitle": "Auth refactor", "sessionId": "abc"},
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "A long recap that would otherwise be the title fallback and exceeds 30 chars.",
                    "timestamp": "2026-01-01T00:05:00Z",
                },
            ],
        )
        svc = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            title = svc.generate_and_cache("/Users/dev/myapp")
        assert title == "Auth refactor"

    def test_falls_back_to_truncated_recap_without_ai_title(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Did some work on the thing.",
                    "timestamp": "2026-01-01T00:05:00Z",
                },
            ],
        )
        svc = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            title = svc.generate_and_cache("/Users/dev/myapp")
        assert title == "Did some work on the thing."

    def test_returns_empty_when_no_recap(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "hi"}, "timestamp": ""}],
        )
        svc = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.generate_and_cache("/Users/dev/myapp")
        assert result == ""

    def test_returns_cached_on_second_call(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Done.",
                    "timestamp": "",
                },
            ],
        )
        svc = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            first = svc.generate_and_cache("/Users/dev/myapp")
            second = svc.generate_and_cache("/Users/dev/myapp")
        assert first == second


class TestNoRecapSkip:
    """Tests for the no-recap skip cache that avoids re-reading unchanged JSONLs."""

    def test_skips_second_call_when_mtime_unchanged(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "work"}, "timestamp": ""}],
        )
        svc = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch.object(svc, "_extract_recap", return_value=None) as mock_extract,
        ):
            svc.generate_and_cache("/Users/dev/myapp")
            svc.generate_and_cache("/Users/dev/myapp")
            assert mock_extract.call_count == 1

    def test_rescans_when_mtime_changes(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        _write_jsonl(jsonl, [{"type": "user", "message": {"content": "work"}, "timestamp": ""}])
        svc = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch.object(svc, "_extract_recap", return_value=None) as mock_extract,
        ):
            svc.generate_and_cache("/Users/dev/myapp")
            os.utime(jsonl, (9999999999, 9999999999))
            svc.generate_and_cache("/Users/dev/myapp")
            assert mock_extract.call_count == 2


class TestCacheSummary:
    def test_cache_and_get(self, tmp_path):
        svc = _make_service(tmp_path)
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            svc.cache("/test", "test summary")
            result = svc.get_cached("/test")
        assert result == "test summary"

    def test_grown_jsonl_invalidates_cache(self, tmp_path):
        svc = _make_service(tmp_path)
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("x" * 20480)

        svc._repo._store_loaded = True
        svc._repo._store = {"/test": SummaryEntry(title="", summary="old", mtime=1.0, jsonl_size=10)}
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.get_cached("/test")
        assert result is None

    def test_newer_mtime_alone_does_not_invalidate_cache(self, tmp_path):
        """Active sessions touch their JSONL constantly; only real growth invalidates."""
        svc = _make_service(tmp_path)
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        svc._repo._store_loaded = True
        svc._repo._store = {"/test": SummaryEntry(title="", summary="old", mtime=1.0, jsonl_size=3)}
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.get_cached("/test")
        assert result == "old"


class TestGetStatus:
    def test_pending_when_uncached(self, tmp_path):
        svc = _make_service(tmp_path)
        assert svc.get_status("/nope") == "pending"

    def test_cached_when_present(self, tmp_path):
        svc = _make_service(tmp_path)
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            svc.cache("/test", "x")
            assert svc.get_status("/test") == "cached"


class TestPriorityQueue:
    def test_track_adds_to_priority_queue(self, tmp_path):
        svc = _make_service(tmp_path)
        svc._repo._store_loaded = True
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")),
            patch.object(svc, "_ensure_bg_thread"),
        ):
            svc.track_session("/new-cwd")
        assert ("/new-cwd", "") in svc._priority_queue

    def test_track_skips_if_cached(self, tmp_path):
        svc = _make_service(tmp_path)
        proj_dir = tmp_path / "projects" / "-cached"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch.object(svc, "_ensure_bg_thread"),
        ):
            svc.cache("/cached", "already done")
            svc.track_session("/cached")
        assert "/cached" not in svc._priority_queue

    def test_pending_count(self, tmp_path):
        svc = _make_service(tmp_path)
        svc._priority_queue.extend([("/a", ""), ("/b", ""), ("/c", "")])
        assert svc.pending_summary_count() == 3


class TestInvalidateCache:
    def test_invalidate_removes_entry(self, tmp_path):
        svc = _make_service(tmp_path)
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            svc.cache("/test", "summary")
            assert svc.get_cached("/test") == "summary"
            svc.invalidate_cache("/test")
            assert svc.get_cached("/test") is None

    def test_invalidate_clears_no_recap_skip(self, tmp_path):
        svc = _make_service(tmp_path)
        svc._no_recap_mtimes["/test"] = 123.0
        svc.invalidate_cache("/test")
        assert "/test" not in svc._no_recap_mtimes
