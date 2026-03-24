"""Tests for JSONL-based attention detection."""

import json
import os
import time
from unittest.mock import patch

from claudewatch.backend.detection.service import _check_jsonl_for_pending_tool


def _write_jsonl(path, entries):
    """Write a list of dicts as JSONL lines to a file."""
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestCheckJsonlForPendingTool:
    """Tests for _check_jsonl_for_pending_tool()."""

    def test_detects_pending_tool_use(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
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
        # Touch file to set age within valid window
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            pending, one_line, ctx = _check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert pending is True
        assert "Bash" in one_line

    def test_user_message_means_not_pending(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
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
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            pending, _, _ = _check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert pending is False

    def test_assistant_without_tool_use_not_pending(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
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
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            pending, _, _ = _check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert pending is False

    def test_too_old_file_ignored(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
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
        os.utime(jsonl, (time.time() - 600, time.time() - 600))  # beyond _JSONL_MAX_AGE (300s)

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            pending, _, _ = _check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert pending is False

    def test_too_fresh_file_ignored(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
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
        # File is 0 seconds old — below _JSONL_MIN_AGE (1s)
        os.utime(jsonl, (time.time(), time.time()))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            pending, _, _ = _check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert pending is False

    def test_nonexistent_project_dir(self, tmp_path):
        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            pending, _, _ = _check_jsonl_for_pending_tool("/Users/dev/nonexistent")
        assert pending is False

    def test_empty_project_dir(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            pending, _, _ = _check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert pending is False

    def test_symlink_traversal_blocked(self, tmp_path):
        """Symlink pointing outside the projects dir should be rejected."""
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        # Create a real JSONL outside projects dir
        evil_dir = tmp_path / "evil"
        evil_dir.mkdir()
        evil_jsonl = evil_dir / "session.jsonl"
        _write_jsonl(
            evil_jsonl,
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
        os.utime(evil_jsonl, (time.time() - 10, time.time() - 10))
        # Symlink from projects dir to evil file
        link = proj_dir / "session.jsonl"
        link.symlink_to(evil_jsonl)

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            pending, _, _ = _check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert pending is False

    def test_progress_message_with_tool_use(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
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
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            pending, one_line, _ = _check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert pending is True
        assert "Edit" in one_line

    def test_skips_system_types(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
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
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            # system is skipped, then assistant with tool_use is found
            pending, _, _ = _check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert pending is True

    def test_malformed_json_skipped(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
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
        os.utime(jsonl, (time.time() - 10, time.time() - 10))

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            pending, _, _ = _check_jsonl_for_pending_tool("/Users/dev/myapp")
        assert pending is True
