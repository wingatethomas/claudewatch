"""Tests for SessionETL — JSONL ingestion into graph nodes."""

import json
import os

import pytest

from claudewatch.backend.graph.models import GraphStore
from claudewatch.backend.graph.repository import SessionETL


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
                    {
                        "type": "tool_use",
                        "id": "tu_2",
                        "name": "Edit",
                        "input": {
                            "file_path": "/src/auth.py",
                            "old_string": "def login():",
                            "new_string": "def login(user):",
                        },
                    },
                ],
                "usage": {"input_tokens": 1000, "output_tokens": 500},
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-03-30T12:00:02Z",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [
                    {"type": "tool_use", "id": "tu_3", "name": "Bash", "input": {"command": "pytest"}},
                    {"type": "text", "text": "See https://github.com/org/repo/pull/42"},
                ],
            },
        },
    ]


@pytest.fixture
def store(tmp_path: str) -> GraphStore:
    return GraphStore(os.path.join(tmp_path, "graph.kuzu"))


@pytest.fixture
def projects_dir(tmp_path: str) -> str:
    proj_dir = os.path.join(tmp_path, "projects", "-Users-dev-myapp")
    _write_jsonl(os.path.join(proj_dir, "sess-1.jsonl"), _make_entries())
    return os.path.join(tmp_path, "projects")


@pytest.fixture
def etl(store: GraphStore, tmp_path: str) -> SessionETL:
    checkpoint_db = os.path.join(tmp_path, "ckpt.db")
    return SessionETL(store.conn, checkpoint_db)


class TestSessionETL:
    def test_ingest_creates_session_node(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (s:Session) RETURN s.id")
        assert result.has_next()
        assert result.get_next()[0] == "sess-1"

    def test_ingest_creates_project_node(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (p:Project) RETURN p.path")
        assert result.has_next()

    def test_ingest_creates_action_nodes(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (a:Action) RETURN count(a)")
        assert result.get_next()[0] == 3  # Read, Edit, Bash

    def test_ingest_creates_file_nodes(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (f:File) RETURN f.path")
        assert result.has_next()
        assert result.get_next()[0] == "/src/auth.py"

    def test_ingest_creates_pr_node(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (pr:PR) RETURN pr.number, pr.repository")
        assert result.has_next()
        row = result.get_next()
        assert row[0] == 42
        assert row[1] == "org/repo"

    def test_performs_edges(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (s:Session)-[:PERFORMS]->(a:Action) RETURN count(a)")
        assert result.get_next()[0] == 3

    def test_targets_edges(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (a:Action)-[:TARGETS]->(f:File) RETURN count(f)")
        assert result.get_next()[0] == 2  # Read + Edit target auth.py

    def test_next_edges(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (a1:Action)-[:NEXT]->(a2:Action) RETURN count(a1)")
        # Read→Edit, Edit→Bash = 2 NEXT edges
        assert result.get_next()[0] == 2

    def test_references_edge(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (s:Session)-[:REFERENCES]->(pr:PR) RETURN pr.number")
        assert result.has_next()
        assert result.get_next()[0] == 42

    def test_in_project_edge(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (s:Session)-[:IN_PROJECT]->(p:Project) RETURN p.path")
        assert result.has_next()

    def test_incremental_skips_unchanged(self, etl: SessionETL, projects_dir: str) -> None:
        stats1 = etl.ingest_all(projects_dir)
        assert "sess-1" in stats1
        stats2 = etl.ingest_all(projects_dir)
        assert len(stats2) == 0

    def test_empty_projects_dir(self, etl: SessionETL, tmp_path: str) -> None:
        stats = etl.ingest_all(os.path.join(tmp_path, "nonexistent"))
        assert len(stats) == 0

    def test_session_tokens_accumulated(self, etl: SessionETL, store: GraphStore, projects_dir: str) -> None:
        etl.ingest_all(projects_dir)
        result = store.conn.execute("MATCH (s:Session {id: 'sess-1'}) RETURN s.input_tokens, s.output_tokens")
        row = result.get_next()
        assert row[0] == 1000  # only one entry has usage
        assert row[1] == 500
