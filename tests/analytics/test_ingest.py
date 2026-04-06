"""Tests for Ingest — JSONL parsing, checkpoints, incremental scanning."""

import json
import os

import pytest

from claudewatch.backend.analytics.ingest import Ingest, _parse_epoch
from claudewatch.backend.analytics.store import (
    AnalyticsStore,
    CheckpointRow,
    EventRow,
    FileRow,
    PullRequestRow,
    SessionRow,
    TokenRow,
    ToolRow,
)


@pytest.fixture
def store(tmp_path: str) -> AnalyticsStore:
    return AnalyticsStore(os.path.join(tmp_path, "test.db"))


@pytest.fixture
def ingest(store: AnalyticsStore) -> Ingest:
    return Ingest(store.session)


def _write_jsonl(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_entries() -> list[dict]:
    return [
        {
            "type": "user",
            "timestamp": "2026-03-30T12:00:00Z",
            "message": {"role": "user", "content": "Fix the bug"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-03-30T12:00:01Z",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [
                    {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/src/auth.py"}},
                    {"type": "tool_use", "id": "tu_2", "name": "Edit", "input": {"file_path": "/src/auth.py"}},
                ],
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cache_creation_input_tokens": 200,
                    "cache_read_input_tokens": 100,
                },
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-03-30T12:00:02Z",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [
                    {"type": "tool_use", "id": "tu_3", "name": "Bash", "input": {"command": "pytest tests/"}},
                    {"type": "text", "text": "Check https://github.com/org/repo/pull/42 for context."},
                ],
                "usage": {"input_tokens": 500, "output_tokens": 200},
            },
        },
        {
            "type": "user",
            "timestamp": "2026-03-30T12:00:03Z",
            "message": {"role": "user", "content": "looks good"},
        },
    ]


@pytest.fixture
def projects_dir(tmp_path: str) -> str:
    proj_dir = os.path.join(tmp_path, "projects", "-Users-dev-myapp")
    os.makedirs(proj_dir)
    _write_jsonl(os.path.join(proj_dir, "abc-1234.jsonl"), _make_entries())
    return os.path.join(tmp_path, "projects")


class TestIngest:
    def test_process_file_counts_entries(self, ingest: Ingest, projects_dir: str) -> None:
        path = os.path.join(projects_dir, "-Users-dev-myapp", "abc-1234.jsonl")
        count = ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        assert count == 4

    def test_events_inserted(self, ingest: Ingest, store: AnalyticsStore, projects_dir: str) -> None:
        path = os.path.join(projects_dir, "-Users-dev-myapp", "abc-1234.jsonl")
        ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        with store.session() as s:
            events = s.query(EventRow).all()
            assert len(events) == 4
            types = [e.entry_type for e in events]
            assert types.count("user") == 2
            assert types.count("assistant") == 2

    def test_tools_extracted(self, ingest: Ingest, store: AnalyticsStore, projects_dir: str) -> None:
        path = os.path.join(projects_dir, "-Users-dev-myapp", "abc-1234.jsonl")
        ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        with store.session() as s:
            tool_rows = s.query(ToolRow).order_by(ToolRow.id).all()
            assert len(tool_rows) == 3
            names = [t.name for t in tool_rows]
            assert "Read" in names
            assert "Edit" in names
            assert "Bash" in names

    def test_files_tracked(self, ingest: Ingest, store: AnalyticsStore, projects_dir: str) -> None:
        path = os.path.join(projects_dir, "-Users-dev-myapp", "abc-1234.jsonl")
        ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        with store.session() as s:
            file_rows = s.query(FileRow).all()
            assert len(file_rows) == 2
            assert all(f.path == "/src/auth.py" for f in file_rows)

    def test_tokens_tracked(self, ingest: Ingest, store: AnalyticsStore, projects_dir: str) -> None:
        path = os.path.join(projects_dir, "-Users-dev-myapp", "abc-1234.jsonl")
        ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        with store.session() as s:
            token_rows = s.query(TokenRow).all()
            assert len(token_rows) == 2
            total_input = sum(t.input for t in token_rows)
            assert total_input == 1500

    def test_pr_extracted(self, ingest: Ingest, store: AnalyticsStore, projects_dir: str) -> None:
        path = os.path.join(projects_dir, "-Users-dev-myapp", "abc-1234.jsonl")
        ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        with store.session() as s:
            prs = s.query(PullRequestRow).all()
            assert len(prs) == 1
            assert prs[0].number == 42
            assert prs[0].repository == "org/repo"

    def test_session_summary_created(self, ingest: Ingest, store: AnalyticsStore, projects_dir: str) -> None:
        path = os.path.join(projects_dir, "-Users-dev-myapp", "abc-1234.jsonl")
        ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        with store.session() as s:
            session = s.get(SessionRow, "abc-1234")
            assert session is not None
            assert session.user_messages == 2
            assert session.asst_messages == 2
            assert session.tool_count == 3
            assert session.input_tokens == 1500
            assert session.primary_model == "claude-opus-4-6"

    def test_checkpoint_created(self, ingest: Ingest, store: AnalyticsStore, projects_dir: str) -> None:
        path = os.path.join(projects_dir, "-Users-dev-myapp", "abc-1234.jsonl")
        ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        with store.session() as s:
            cp = s.get(CheckpointRow, path)
            assert cp is not None
            assert cp.byte_offset > 0

    def test_incremental_skips_unchanged(self, ingest: Ingest, projects_dir: str) -> None:
        path = os.path.join(projects_dir, "-Users-dev-myapp", "abc-1234.jsonl")
        count1 = ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        assert count1 == 4
        count2 = ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        assert count2 == 0

    def test_incremental_picks_up_new_lines(self, ingest: Ingest, projects_dir: str) -> None:
        path = os.path.join(projects_dir, "-Users-dev-myapp", "abc-1234.jsonl")
        ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        with open(path, "a") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-03-30T12:00:04Z",
                        "message": {"role": "user", "content": "one more"},
                    }
                )
                + "\n"
            )
        count = ingest.process_file(path, "abc-1234", "-Users-dev-myapp")
        assert count == 1

    def test_full_scan_processes_all(self, ingest: Ingest, projects_dir: str) -> None:
        stats = ingest.full_scan(projects_dir)
        assert "abc-1234" in stats
        assert stats["abc-1234"] == 4

    def test_incremental_scan(self, ingest: Ingest, projects_dir: str) -> None:
        ingest.full_scan(projects_dir)
        stats = ingest.incremental_scan(projects_dir)
        assert len(stats) == 0

    def test_handles_corrupt_jsonl(self, ingest: Ingest, tmp_path: str) -> None:
        path = os.path.join(tmp_path, "bad.jsonl")
        with open(path, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {}}) + "\n")
            f.write("{truncated\n")
        count = ingest.process_file(path, "test", "test-proj", incremental=False)
        assert count == 1

    def test_handles_missing_file(self, ingest: Ingest) -> None:
        count = ingest.process_file("/nonexistent/file.jsonl", "x", "x")
        assert count == 0

    def test_bash_command_truncated(self, ingest: Ingest, store: AnalyticsStore, tmp_path: str) -> None:
        path = os.path.join(tmp_path, "cmd.jsonl")
        long_cmd = "x" * 500
        _write_jsonl(
            path,
            [
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "model": "claude-opus-4-6",
                        "content": [{"type": "tool_use", "name": "Bash", "input": {"command": long_cmd}}],
                    },
                }
            ],
        )
        ingest.process_file(path, "s1", "p1", incremental=False)
        with store.session() as s:
            tool = s.query(ToolRow).first()
            assert len(tool.command) == 200

    def test_synthetic_model_ignored(self, ingest: Ingest, store: AnalyticsStore, tmp_path: str) -> None:
        path = os.path.join(tmp_path, "synth.jsonl")
        _write_jsonl(
            path,
            [
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "model": "<synthetic>",
                        "content": [{"type": "text", "text": "hi"}],
                    },
                }
            ],
        )
        ingest.process_file(path, "s1", "p1", incremental=False)
        with store.session() as s:
            event = s.query(EventRow).first()
            assert event.model is None


class TestParseEpoch:
    def test_iso_with_tz(self) -> None:
        epoch = _parse_epoch("2026-03-30T12:00:00Z")
        assert epoch > 0

    def test_iso_without_tz(self) -> None:
        epoch = _parse_epoch("2026-03-30T12:00:00")
        assert epoch > 0

    def test_empty_string(self) -> None:
        assert _parse_epoch("") == 0.0

    def test_invalid_string(self) -> None:
        assert _parse_epoch("not-a-date") == 0.0
