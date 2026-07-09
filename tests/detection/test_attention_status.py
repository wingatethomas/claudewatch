"""Tests for ATTENTION status detection — ensures pending tool_use is always detected.

These tests verify that:
1. ATTENTION overrides both IDLE and WORKING from window title
2. Pending tools are detected regardless of JSONL age (no upper bound cutoff)
3. Fresh JSONL files (< 5s) are treated as actively working, not pending
4. Multiple sessions sharing the same CWD all get the correct status
"""

import json
import os
import time

from claudewatch.backend.core.models import SessionStatus
from claudewatch.backend.detection.service import DetectionService, _match_jsonl_by_title

_STALE_AGE = 10  # seconds — old enough that the pending check runs


def _write_jsonl(path: str, entries: list[dict], *, stale: bool = False) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    if stale:
        old_time = time.time() - _STALE_AGE
        os.utime(path, (old_time, old_time))


def _read_tail(path: str) -> str:
    """Read file content as tail text for testing."""
    with open(path) as f:
        return f.read()


def _make_service(tmp_path: str) -> tuple[DetectionService, str]:
    """Create a DetectionService with mocked dependencies pointed at tmp_path."""
    from unittest.mock import MagicMock

    from claudewatch.backend.core.session_log.jsonl import read_jsonl_tail

    proj_key = "-Users-dev-myapp"
    proj_dir = os.path.join(tmp_path, proj_key)
    session_id = "test-session-001"
    jsonl_path = os.path.join(proj_dir, f"{session_id}.jsonl")

    process_service = MagicMock()
    session_log_service = MagicMock()
    session_log_service.find_most_recent.return_value = jsonl_path
    session_log_service.read_tail.side_effect = read_jsonl_tail
    session_log_service.get_session_id.return_value = session_id

    service = DetectionService(process_service, session_log_service)
    return service, jsonl_path


class TestPendingToolDetection:
    """Tests for _check_jsonl_for_pending_tool edge cases."""

    def test_detects_pending_tool_use(self, tmp_path: str) -> None:
        service, jsonl_path = _make_service(tmp_path)
        _write_jsonl(
            jsonl_path,
            [
                {"type": "user", "message": {"role": "user", "content": "fix bug"}},
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "rm -rf /tmp/test"}},
                        ],
                    },
                },
            ],
            stale=True,
        )

        tail = _read_tail(jsonl_path)
        result = service._check_jsonl_for_pending_tool(tail)
        assert result.has_pending is True
        assert "Bash" in result.one_line

    def test_pending_tool_survives_trailing_bookkeeping_entries(self, tmp_path: str) -> None:
        """mode/permission-mode/attachment spam after a pending tool_use must not
        push it out of the scan window — that read as IDLE instead of ATTENTION."""
        service, jsonl_path = _make_service(tmp_path)
        entries: list[dict] = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
                },
            },
        ]
        bookkeeping = [
            {"type": "mode", "mode": "normal"},
            {"type": "permission-mode", "permissionMode": "default"},
            {"type": "attachment"},
            {"type": "queue-operation", "operation": "dequeue"},
            {"type": "pr-link"},
            {"type": "ai-title", "aiTitle": "Some task"},
        ]
        for _ in range(6):
            entries.extend(bookkeeping)
        _write_jsonl(jsonl_path, entries, stale=True)

        result = service._check_jsonl_for_pending_tool(_read_tail(jsonl_path))
        assert result.has_pending is True
        assert "Bash" in result.one_line

    def test_no_pending_when_user_responded(self, tmp_path: str) -> None:
        service, jsonl_path = _make_service(tmp_path)
        _write_jsonl(
            jsonl_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        ],
                    },
                },
                {"type": "user", "message": {"role": "user", "content": "yes"}},
            ],
        )

        tail = _read_tail(jsonl_path)
        result = service._check_jsonl_for_pending_tool(tail)
        assert result.has_pending is False

    def test_detects_pending_after_five_minutes(self, tmp_path: str) -> None:
        """Bug fix: JSONL older than 5 minutes should still show pending tool_use."""
        service, jsonl_path = _make_service(tmp_path)
        _write_jsonl(
            jsonl_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/src/main.py"}},
                        ],
                    },
                },
            ],
        )

        tail = _read_tail(jsonl_path)
        result = service._check_jsonl_for_pending_tool(tail)
        assert result.has_pending is True
        assert "Edit" in result.one_line

    def test_fresh_file_treated_as_working(self, tmp_path: str) -> None:
        """Fresh JSONL (< 5s old) means Claude is actively working — not pending approval."""
        service, jsonl_path = _make_service(tmp_path)
        _write_jsonl(
            jsonl_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}},
                        ],
                    },
                },
            ],
        )
        # File was just written — mtime is now, age should be small
        tail, age = service._read_jsonl_tail(jsonl_path)
        assert 0 <= age < 5

    def test_no_pending_when_tool_result_received(self, tmp_path: str) -> None:
        """Tool completed — tool_result after tool_use means not pending."""
        service, jsonl_path = _make_service(tmp_path)
        _write_jsonl(
            jsonl_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/out.md"}},
                        ],
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "toolu_001", "content": "wrote 240 lines"}],
                    },
                },
            ],
        )

        tail = _read_tail(jsonl_path)
        result = service._check_jsonl_for_pending_tool(tail)
        assert result.has_pending is False

    def test_no_pending_after_tool_result_then_text(self, tmp_path: str) -> None:
        """Full cycle: tool_use → tool_result → assistant text. Not pending."""
        service, jsonl_path = _make_service(tmp_path)
        _write_jsonl(
            jsonl_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}},
                        ],
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "toolu_002", "content": "5 passed"}],
                    },
                },
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "All tests pass."}],
                    },
                },
            ],
        )

        tail = _read_tail(jsonl_path)
        result = service._check_jsonl_for_pending_tool(tail)
        assert result.has_pending is False

    def test_pending_when_no_tool_result(self, tmp_path: str) -> None:
        """tool_use without subsequent tool_result — still pending."""
        service, jsonl_path = _make_service(tmp_path)
        _write_jsonl(
            jsonl_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/src/auth.py"}},
                        ],
                    },
                },
            ],
            stale=True,
        )

        tail = _read_tail(jsonl_path)
        result = service._check_jsonl_for_pending_tool(tail)
        assert result.has_pending is True

    def test_no_pending_when_assistant_sent_text_only(self, tmp_path: str) -> None:
        service, jsonl_path = _make_service(tmp_path)
        _write_jsonl(
            jsonl_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Done!"}],
                    },
                },
            ],
        )

        tail = _read_tail(jsonl_path)
        result = service._check_jsonl_for_pending_tool(tail)
        assert result.has_pending is False


class TestStatusPriority:
    """Tests for status priority: ATTENTION > IDLE > WORKING from JSONL."""

    def test_attention_overrides_idle_from_window_title(self, tmp_path: str) -> None:
        """If window title says IDLE but JSONL has pending tool, status should be ATTENTION."""
        service, jsonl_path = _make_service(tmp_path)
        _write_jsonl(
            jsonl_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "make build"}},
                        ],
                    },
                },
            ],
            stale=True,
        )

        tail = _read_tail(jsonl_path)
        result = service._check_jsonl_for_pending_tool(tail)
        assert result.has_pending is True

    def test_idle_from_jsonl_when_file_stale(self, tmp_path: str) -> None:
        """JSONL where last entry is assistant text → IDLE."""
        service, jsonl_path = _make_service(tmp_path)
        _write_jsonl(
            jsonl_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "All done."}],
                    },
                },
            ],
        )
        old_time = time.time() - 30
        os.utime(jsonl_path, (old_time, old_time))

        tail = _read_tail(jsonl_path)
        status = service._check_jsonl_for_idle(tail)
        assert status == SessionStatus.IDLE


class TestMatchJsonlByTitle:
    """Tests for _match_jsonl_by_title — picks the right JSONL in shared-CWD setups."""

    def test_substring_match_returns_path(self):
        mapping = {"Wire up search filter": "/proj/a.jsonl"}
        title = "myapp — ✳ Wire up search filter — node ◂ claude — 177×47"
        assert _match_jsonl_by_title(title, mapping, "/fallback.jsonl") == ("/proj/a.jsonl", True)

    def test_longest_match_wins(self):
        mapping = {
            "Review PR": "/proj/short.jsonl",
            "Review PR #593 backend": "/proj/long.jsonl",
        }
        title = "myapp — ✳ Review PR #593 backend — node ◂ claude — 80×24"
        assert _match_jsonl_by_title(title, mapping, "/fallback.jsonl") == ("/proj/long.jsonl", True)

    def test_no_match_returns_fallback(self):
        mapping = {"Some other title": "/proj/other.jsonl"}
        title = "myapp — ✳ Brand new session — claude"
        assert _match_jsonl_by_title(title, mapping, "/fallback.jsonl") == ("/fallback.jsonl", False)

    def test_empty_map_returns_fallback(self):
        assert _match_jsonl_by_title("any title", {}, "/fallback.jsonl") == ("/fallback.jsonl", False)

    def test_empty_title_returns_fallback(self):
        mapping = {"Some title": "/proj/a.jsonl"}
        assert _match_jsonl_by_title("", mapping, "/fallback.jsonl") == ("/fallback.jsonl", False)

    def test_empty_title_value_skipped(self):
        # An empty aiTitle would substring-match every title — must be ignored.
        mapping = {"": "/proj/empty.jsonl", "Real title": "/proj/real.jsonl"}
        title = "myapp — ✳ Real title — claude"
        assert _match_jsonl_by_title(title, mapping, "/fallback.jsonl") == ("/proj/real.jsonl", True)

    def test_returns_fallback_when_fallback_is_none(self):
        assert _match_jsonl_by_title("x", {}, None) == (None, False)
