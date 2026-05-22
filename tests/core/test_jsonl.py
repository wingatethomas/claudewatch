"""Tests for JSONL-based attention detection."""

import json
from unittest.mock import MagicMock

from claudewatch.backend.core.process.service import ProcessService
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.detection.service import DetectionService


def _write_jsonl(path, entries):
    """Write a list of dicts as JSONL lines to a file."""
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_service(jsonl_path=None, tail=None):
    """Create a DetectionService with mocked dependencies."""
    mock_log = MagicMock(spec=SessionLogService)
    mock_log.find_most_recent.return_value = jsonl_path
    mock_log.read_tail.return_value = tail or ""
    mock_proc = MagicMock(spec=ProcessService)
    return DetectionService(mock_proc, mock_log)


class TestCheckJsonlForPendingTool:
    """Tests for DetectionService._check_jsonl_for_pending_tool()."""

    def test_detects_pending_tool_use(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        ]
                    },
                },
            ],
        )

        result = _make_service()._check_jsonl_for_pending_tool(jsonl.read_text())
        assert result.has_pending is True
        assert "Bash" in result.one_line

    def test_user_message_means_not_pending(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        ]
                    },
                },
                {"type": "user", "message": {"content": "yes"}},
            ],
        )

        result = _make_service()._check_jsonl_for_pending_tool(jsonl.read_text())
        assert result.has_pending is False

    def test_assistant_without_tool_use_not_pending(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Done!"},
                        ]
                    },
                },
            ],
        )

        result = _make_service()._check_jsonl_for_pending_tool(jsonl.read_text())
        assert result.has_pending is False

    def test_old_file_still_detected(self, tmp_path):
        """Pending tools are detected even if JSONL is hours old — user may step away."""
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        ]
                    },
                },
            ],
        )

        result = _make_service()._check_jsonl_for_pending_tool(jsonl.read_text())
        assert result.has_pending is True

    def test_fresh_file_has_small_age(self, tmp_path):
        """Fresh JSONL (< 5s) means _read_jsonl_tail returns a small age.
        The caller (detect loop) uses age to decide streaming vs idle."""
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        ]
                    },
                },
            ],
        )

        svc = _make_service(str(jsonl), jsonl.read_text())
        _, age = svc._read_jsonl_tail(str(jsonl))
        assert 0 <= age < 5

    def test_nonexistent_project_dir(self):
        result = _make_service()._check_jsonl_for_pending_tool("")
        assert result.has_pending is False

    def test_empty_project_dir(self):
        result = _make_service()._check_jsonl_for_pending_tool("")
        assert result.has_pending is False

    def test_progress_message_with_tool_use(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {
                    "type": "progress",
                    "data": {
                        "message": {
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/foo.py"}},
                                ]
                            },
                        }
                    },
                },
            ],
        )

        result = _make_service()._check_jsonl_for_pending_tool(jsonl.read_text())
        assert result.has_pending is True
        assert "Edit" in result.one_line

    def test_skips_system_types(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(
            jsonl,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        ]
                    },
                },
                {"type": "system", "data": {}},
            ],
        )

        result = _make_service()._check_jsonl_for_pending_tool(jsonl.read_text())
        assert result.has_pending is True

    def test_malformed_json_skipped(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write("not json\n")
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                            ]
                        },
                    }
                )
                + "\n"
            )

        result = _make_service()._check_jsonl_for_pending_tool(jsonl.read_text())
        assert result.has_pending is True
