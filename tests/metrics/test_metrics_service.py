"""Tests for MetricsService — aggregate session insights from JSONL."""

import json
import os

import pytest

from claudewatch.backend.metrics.service import SessionMetrics


@pytest.fixture
def sample_jsonl(tmp_path: str) -> str:
    """Create a sample JSONL file with realistic content."""
    entries = [
        {"type": "user", "message": {"role": "user", "content": "Fix the login bug"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "/src/auth.py"}},
                ],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [
                    {"type": "tool_use", "name": "Edit", "input": {"file_path": "/src/auth.py"}},
                ],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}},
                ],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [
                    {"type": "tool_use", "name": "Agent", "input": {"prompt": "run tests"}},
                ],
            },
        },
        {"type": "user", "message": {"role": "user", "content": "looks good"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "Done!"}],
            },
        },
    ]
    path = os.path.join(tmp_path, "session.jsonl")
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return path


class TestSessionMetrics:
    def test_parse_from_jsonl(self, sample_jsonl: str) -> None:
        metrics = SessionMetrics.from_jsonl(sample_jsonl)
        assert metrics is not None

    def test_counts_user_messages(self, sample_jsonl: str) -> None:
        metrics = SessionMetrics.from_jsonl(sample_jsonl)
        assert metrics.user_messages == 2

    def test_counts_assistant_messages(self, sample_jsonl: str) -> None:
        metrics = SessionMetrics.from_jsonl(sample_jsonl)
        assert metrics.assistant_messages == 5

    def test_extracts_tools(self, sample_jsonl: str) -> None:
        metrics = SessionMetrics.from_jsonl(sample_jsonl)
        assert metrics.tools["Read"] == 1
        assert metrics.tools["Edit"] == 1
        assert metrics.tools["Bash"] == 1
        assert metrics.tools["Agent"] == 1

    def test_extracts_models(self, sample_jsonl: str) -> None:
        metrics = SessionMetrics.from_jsonl(sample_jsonl)
        assert "claude-opus-4-6" in metrics.models
        assert "claude-sonnet-4-6" in metrics.models

    def test_counts_agent_spawns(self, sample_jsonl: str) -> None:
        metrics = SessionMetrics.from_jsonl(sample_jsonl)
        assert metrics.agent_spawns == 1

    def test_counts_files_touched(self, sample_jsonl: str) -> None:
        metrics = SessionMetrics.from_jsonl(sample_jsonl)
        assert "/src/auth.py" in metrics.files_touched

    def test_empty_file(self, tmp_path: str) -> None:
        path = os.path.join(tmp_path, "empty.jsonl")
        open(path, "w").close()  # noqa: SIM115
        metrics = SessionMetrics.from_jsonl(path)
        assert metrics.user_messages == 0
        assert metrics.assistant_messages == 0
        assert len(metrics.tools) == 0
