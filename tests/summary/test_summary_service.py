"""Tests for claudewatch.backend.summary.service.SummaryService."""

import json
import os
import subprocess
from unittest.mock import MagicMock, patch

from claudewatch.backend.core.process.service import ProcessService
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.summary.models import SummaryEntry
from claudewatch.backend.summary.service import SummaryService, _parse_summary_response


class TestParseSummaryResponse:
    def test_valid_title_and_bullets(self) -> None:
        raw = "TITLE: Refactoring auth module\n• Updated login flow\n• Fixed token refresh\n• Added tests"
        title, bullets = _parse_summary_response(raw)
        assert title == "Refactoring auth module"
        assert "Updated login flow" in bullets
        assert "Fixed token refresh" in bullets

    def test_title_clamped_to_30_chars(self) -> None:
        raw = "TITLE: This is a very long title that should be truncated at word boundary\n• bullet"
        title, _ = _parse_summary_response(raw)
        assert len(title) <= 30

    def test_case_insensitive_title(self) -> None:
        raw = "title: lowercase works\n• bullet"
        title, _ = _parse_summary_response(raw)
        assert title == "lowercase works"

    def test_dash_bullets(self) -> None:
        raw = "TITLE: Test\n- dash bullet one\n- dash bullet two"
        _, bullets = _parse_summary_response(raw)
        assert "dash bullet one" in bullets
        assert "dash bullet two" in bullets

    def test_fallback_first_line_as_title(self) -> None:
        raw = "Just a plain response\nwith some lines"
        title, _ = _parse_summary_response(raw)
        assert title == "Just a plain response"

    def test_fallback_lines_as_bullets(self) -> None:
        raw = "TITLE: Something\nno bullet markers here\njust plain text\nanother line"
        _, bullets = _parse_summary_response(raw)
        assert "no bullet markers here" in bullets

    def test_rejects_prompt_echo(self) -> None:
        raw = "present-tense verb phrase, max 30 chars\n• bullet"
        title, bullets = _parse_summary_response(raw)
        assert title == ""
        assert bullets == ""

    def test_rejects_no_structure(self) -> None:
        raw = ""
        title, bullets = _parse_summary_response(raw)
        assert title == ""
        assert bullets == ""

    def test_bullets_only_gets_first_as_title(self) -> None:
        raw = "• First action taken\n• Second action\n• Third"
        title, bullets = _parse_summary_response(raw)
        assert title == "First action taken"


def _make_service(tmp_path, projects_dir=None):
    """Create a SummaryService wired to tmp_path fixtures."""
    from claudewatch.backend.summary.repository import SummaryRepository

    session_log_service = SessionLogService()
    process_service = ProcessService()
    store_path = str(tmp_path / "summaries.json")
    repo = SummaryRepository(session_log_service, store_path=store_path)
    return SummaryService(repo, session_log_service, process_service), projects_dir


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
        assert "USER: fix the login bug" in result

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
        assert "ASSISTANT: I'll help you fix that" in result

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
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_recap("/Users/dev/myapp")
        assert result == "Fixed auth middleware and added tests."

    def test_returns_most_recent_recap(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Old recap.",
                    "timestamp": "2026-01-01T00:00:00Z",
                },
                {"type": "user", "message": {"content": "more work"}, "timestamp": ""},
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Newer recap after more work.",
                    "timestamp": "2026-01-01T01:00:00Z",
                },
            ],
        )
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_recap("/Users/dev/myapp")
        assert result == "Newer recap after more work."

    def test_returns_none_when_no_recap(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "hello"}, "timestamp": ""}],
        )
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_recap("/Users/dev/myapp")
        assert result is None

    def test_returns_none_for_missing_project(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            result = svc._extract_recap("/Users/dev/myapp")
        assert result is None

    def test_ignores_other_system_subtypes(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "system", "subtype": "other_thing", "content": "not a recap", "timestamp": ""},
            ],
        )
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_recap("/Users/dev/myapp")
        assert result is None

    def test_skips_empty_recap_content(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "system", "subtype": "away_summary", "content": "", "timestamp": ""},
            ],
        )
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_recap("/Users/dev/myapp")
        assert result is None

    def test_generate_uses_recap_over_claude_p(self, tmp_path):
        """generate_and_cache should use native recap instead of spawning claude -p."""
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
        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.generate_and_cache("/Users/dev/myapp")
            assert result  # got a title back
            # Full recap should be in the cached summary
            cached = svc.get_cached_summary("/Users/dev/myapp")
            assert cached == "Fixed auth middleware and added integration tests."

    def test_generate_skips_claude_p_when_feature_off(self, tmp_path):
        """With background_summaries off and no recap, generate_and_cache returns empty without subprocess."""
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "fix auth"}, "timestamp": ""}],
        )
        svc, _ = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch("claudewatch.backend.summary.service.features.is_enabled", return_value=False),
            patch.object(svc, "_call_claude") as mock_claude,
        ):
            result = svc.generate_and_cache("/Users/dev/myapp")
            mock_claude.assert_not_called()
        assert result == ""

    def test_generate_uses_recap_even_when_feature_off(self, tmp_path):
        """Native recaps work regardless of the background_summaries toggle."""
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [
                {"type": "user", "message": {"content": "fix auth"}, "timestamp": ""},
                {
                    "type": "system",
                    "subtype": "away_summary",
                    "content": "Fixed auth middleware.",
                    "timestamp": "2026-01-01T00:05:00Z",
                },
            ],
        )
        svc, _ = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch("claudewatch.backend.summary.service.features.is_enabled", return_value=False),
            patch.object(svc, "_call_claude") as mock_claude,
        ):
            result = svc.generate_and_cache("/Users/dev/myapp")
            mock_claude.assert_not_called()
        assert result  # recap title returned


class TestNoRecapSkip:
    """Tests for the no-recap skip cache that avoids re-reading unchanged JSONLs."""

    def test_skips_second_call_when_mtime_unchanged(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "work"}, "timestamp": ""}],
        )
        svc, _ = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch("claudewatch.backend.summary.service.features.is_enabled", return_value=False),
            patch.object(svc, "_extract_recap", return_value=None) as mock_extract,
        ):
            svc.generate_and_cache("/Users/dev/myapp")
            svc.generate_and_cache("/Users/dev/myapp")
            # First call scans; second call should skip
            assert mock_extract.call_count == 1

    def test_rescans_when_mtime_changes(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        _write_jsonl(jsonl, [{"type": "user", "message": {"content": "work"}, "timestamp": ""}])
        svc, _ = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch("claudewatch.backend.summary.service.features.is_enabled", return_value=False),
            patch.object(svc, "_extract_recap", return_value=None) as mock_extract,
        ):
            svc.generate_and_cache("/Users/dev/myapp")
            # Bump mtime
            os.utime(jsonl, (9999999999, 9999999999))
            svc.generate_and_cache("/Users/dev/myapp")
            assert mock_extract.call_count == 2


class TestFailureTracking:
    """Tests for the _failures counting and MAX_FAILURES threshold."""

    def test_increments_on_empty_claude_response(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "work"}, "timestamp": ""}],
        )
        svc, _ = _make_service(tmp_path)
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch("claudewatch.backend.summary.service.features.is_enabled", return_value=True),
            patch.object(svc, "_call_claude", return_value=""),
        ):
            svc.generate_and_cache("/Users/dev/myapp")
            assert svc._failures["/Users/dev/myapp"][0] == 1
            svc.generate_and_cache("/Users/dev/myapp")
            assert svc._failures["/Users/dev/myapp"][0] == 2

    def test_resets_failures_on_success(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "work"}, "timestamp": ""}],
        )
        svc, _ = _make_service(tmp_path)
        svc._failures["/Users/dev/myapp"] = (2, 100.0)
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch("claudewatch.backend.summary.service.features.is_enabled", return_value=True),
            patch.object(svc, "_call_claude", return_value="TITLE: Done\n• did a thing"),
        ):
            svc.generate_and_cache("/Users/dev/myapp")
        assert "/Users/dev/myapp" not in svc._failures

    def test_gives_up_after_max_failures(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "work"}, "timestamp": ""}],
        )
        svc, _ = _make_service(tmp_path)
        # Seed with MAX_FAILURES threshold already reached at current mtime
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            mtime = svc._repo.get_jsonl_mtime("/Users/dev/myapp")
        svc._failures["/Users/dev/myapp"] = (5, mtime)
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch("claudewatch.backend.summary.service.features.is_enabled", return_value=True),
            patch.object(svc, "_call_claude") as mock_claude,
        ):
            result = svc.generate_and_cache("/Users/dev/myapp")
            mock_claude.assert_not_called()
        assert result == ""

    def test_retries_after_mtime_advances_past_failure(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_jsonl(
            proj_dir / "session.jsonl",
            [{"type": "user", "message": {"content": "work"}, "timestamp": ""}],
        )
        svc, _ = _make_service(tmp_path)
        # Seed failures at an old mtime — newer mtime should trigger retry
        svc._failures["/Users/dev/myapp"] = (5, 100.0)
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch("claudewatch.backend.summary.service.features.is_enabled", return_value=True),
            patch.object(svc, "_call_claude", return_value="TITLE: Recovered\n• got a response"),
        ):
            result = svc.generate_and_cache("/Users/dev/myapp")
        assert result  # should have tried and succeeded
        assert "/Users/dev/myapp" not in svc._failures


class TestExtractRecapFullScan:
    """Verify the full-scan fallback catches recaps outside the 200KB tail window."""

    def test_full_scan_finds_recap_past_tail(self, tmp_path):
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
        # Pad with many user messages to push recap past the 200KB tail window
        filler = {"type": "user", "message": {"content": "x" * 500}, "timestamp": ""}
        entries.extend([filler] * 500)  # ~250KB of filler
        _write_jsonl(proj_dir / "session.jsonl", entries)

        svc, _ = _make_service(tmp_path)
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc._extract_recap("/Users/dev/myapp")
        assert result == "Early recap deep in the file."


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


class TestCacheSummary:
    def test_cache_and_get(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            svc.cache("/test", "test summary")
            result = svc.get_cached("/test")
        assert result == "test summary"

    def test_stale_cache_returns_none(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        svc._repo._store_loaded = True
        svc._repo._store = {"/test": SummaryEntry(title="", summary="old", mtime=1.0)}
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = svc.get_cached("/test")
        assert result is None


class TestIsGenerating:
    def test_false_when_not_generating(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        assert svc.is_generating("/test") is False

    def test_true_when_generating(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        svc._in_progress.add("/test")
        assert svc.is_generating("/test") is True


class TestPriorityQueue:
    def test_track_adds_to_priority_queue(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        svc._repo._store_loaded = True
        with (
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")),
            patch.object(svc, "_ensure_bg_thread"),
        ):
            svc.track_session("/new-cwd")
        assert ("/new-cwd", "") in svc._priority_queue

    def test_track_skips_if_cached(self, tmp_path):
        svc, _ = _make_service(tmp_path)
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
        svc, _ = _make_service(tmp_path)
        svc._priority_queue.extend([("/a", ""), ("/b", ""), ("/c", "")])
        assert svc.pending_summary_count() == 3


class TestInvalidateCache:
    def test_invalidate_removes_entry(self, tmp_path):
        svc, _ = _make_service(tmp_path)
        proj_dir = tmp_path / "projects" / "-test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            svc.cache("/test", "summary")
            assert svc.get_cached("/test") == "summary"
            svc.invalidate_cache("/test")
            assert svc.get_cached("/test") is None
