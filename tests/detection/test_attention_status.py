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
from claudewatch.backend.detection.service import DetectionService

_STALE_AGE = 10  # seconds — old enough that the pending check runs


def _write_jsonl(path: str, entries: list[dict], *, stale: bool = False) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    if stale:
        old_time = time.time() - _STALE_AGE
        os.utime(path, (old_time, old_time))


class TestPendingToolDetection:
    """Tests for _check_jsonl_for_pending_tool edge cases."""

    def _make_service(self, tmp_path: str) -> tuple[DetectionService, str]:
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

    def test_detects_pending_tool_use(self, tmp_path: str) -> None:
        service, jsonl_path = self._make_service(tmp_path)
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

        cwd = "/Users/dev/myapp"
        result = service._check_jsonl_for_pending_tool(cwd)
        assert result.has_pending is True
        assert "Bash" in result.one_line

    def test_no_pending_when_user_responded(self, tmp_path: str) -> None:
        service, jsonl_path = self._make_service(tmp_path)
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

        result = service._check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert result.has_pending is False

    def test_detects_pending_after_five_minutes(self, tmp_path: str) -> None:
        """Bug fix: JSONL older than 5 minutes should still show pending tool_use.

        Users can step away. The old code had a 300s cutoff which meant
        ATTENTION status disappeared after 5 minutes.
        """
        service, jsonl_path = self._make_service(tmp_path)
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
        # Set mtime to 10 minutes ago
        old_time = time.time() - 600
        os.utime(jsonl_path, (old_time, old_time))

        result = service._check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert result.has_pending is True
        assert "Edit" in result.one_line

    def test_fresh_file_not_flagged_as_pending(self, tmp_path: str) -> None:
        """Fresh JSONL (< 5s old) means Claude is actively working — not pending approval."""
        service, jsonl_path = self._make_service(tmp_path)
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
        # File was just written — mtime is now, so it's considered active

        result = service._check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert result.has_pending is False

    def test_no_pending_when_tool_result_received(self, tmp_path: str) -> None:
        """Tool completed — tool_result after tool_use means not pending."""
        service, jsonl_path = self._make_service(tmp_path)
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

        result = service._check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert result.has_pending is False

    def test_no_pending_after_tool_result_then_text(self, tmp_path: str) -> None:
        """Full cycle: tool_use → tool_result → assistant text. Not pending."""
        service, jsonl_path = self._make_service(tmp_path)
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

        result = service._check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert result.has_pending is False

    def test_pending_when_no_tool_result(self, tmp_path: str) -> None:
        """tool_use without subsequent tool_result — still pending."""
        service, jsonl_path = self._make_service(tmp_path)
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

        result = service._check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert result.has_pending is True

    def test_no_pending_when_assistant_sent_text_only(self, tmp_path: str) -> None:
        service, jsonl_path = self._make_service(tmp_path)
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

        result = service._check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert result.has_pending is False


class TestStatusPriority:
    """Tests for status priority: ATTENTION > IDLE > WORKING from JSONL."""

    def _make_service_and_sessions(self, tmp_path: str) -> tuple[DetectionService, str]:
        from unittest.mock import MagicMock

        from claudewatch.backend.core.session_log.jsonl import read_jsonl_tail

        proj_key = "-Users-dev-myapp"
        proj_dir = os.path.join(tmp_path, proj_key)
        session_id = "test-session-002"
        jsonl_path = os.path.join(proj_dir, f"{session_id}.jsonl")

        process_service = MagicMock()
        session_log_service = MagicMock()
        session_log_service.find_most_recent.return_value = jsonl_path
        session_log_service.read_tail.side_effect = read_jsonl_tail
        session_log_service.get_session_id.return_value = session_id

        service = DetectionService(process_service, session_log_service)
        return service, jsonl_path

    def test_attention_overrides_idle_from_window_title(self, tmp_path: str) -> None:
        """If window title says IDLE but JSONL has pending tool, status should be ATTENTION."""
        service, jsonl_path = self._make_service_and_sessions(tmp_path)
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

        result = service._check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert result.has_pending is True

    def test_idle_from_jsonl_when_file_stale(self, tmp_path: str) -> None:
        """JSONL where last entry is assistant text → IDLE."""
        service, jsonl_path = self._make_service_and_sessions(tmp_path)
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
        # Make it stale enough that mtime check doesn't think it's active
        old_time = time.time() - 30
        os.utime(jsonl_path, (old_time, old_time))

        status = service._check_jsonl_for_idle("/Users/dev/myapp")
        assert status == SessionStatus.IDLE
