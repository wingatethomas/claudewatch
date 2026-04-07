"""Tests for GraphService — facade wiring."""

import json
import os

import pytest

from claudewatch.backend.graph.service import GraphService


def _write_jsonl(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


@pytest.fixture
def projects_dir(tmp_path: str) -> str:
    proj_dir = os.path.join(tmp_path, "projects", "-Users-dev-app")
    _write_jsonl(
        os.path.join(proj_dir, "sess-1.jsonl"),
        [
            {
                "type": "user",
                "timestamp": "2026-03-30T12:00:00Z",
                "message": {"role": "user", "content": "hello"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-03-30T12:00:01Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-4-6",
                    "content": [
                        {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/src/main.py"}},
                    ],
                },
            },
        ],
    )
    return os.path.join(tmp_path, "projects")


@pytest.fixture
def service(tmp_path: str, projects_dir: str) -> GraphService:
    db_path = os.path.join(tmp_path, "graph.kuzu")
    return GraphService(db_path, projects_dir)


class TestGraphService:
    def test_ingest_sessions(self, service: GraphService) -> None:
        stats = service.ingest_sessions()
        assert "sess-1" in stats

    def test_full_pipeline(self, service: GraphService) -> None:
        stats = service.full_pipeline()
        assert "sess-1" in stats

    def test_queries_property(self, service: GraphService) -> None:
        service.ingest_sessions()
        chain = service.queries.intent_chain("sess-1")
        assert len(chain) >= 1

    def test_map_edits_empty(self, service: GraphService) -> None:
        assert service.map_edits() == 0

    def test_index_code_nonexistent(self, service: GraphService) -> None:
        assert service.index_code("/nonexistent/path") == 0

    def test_close(self, service: GraphService) -> None:
        service.close()
