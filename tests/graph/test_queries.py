"""Tests for GraphQueries — Cypher queries against populated graph."""

import json
import os

import pytest

from claudewatch.backend.graph.models import (
    ActionStep,
    GraphStore,
    ImpactResult,
    ProjectGraphResult,
    WorkflowPattern,
)
from claudewatch.backend.graph.repository import GraphQueries, SessionETL


def _write_jsonl(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


@pytest.fixture
def store(tmp_path: str) -> GraphStore:
    return GraphStore(os.path.join(tmp_path, "graph.kuzu"))


@pytest.fixture
def queries(store: GraphStore) -> GraphQueries:
    return GraphQueries(store.conn)


@pytest.fixture
def populated(store: GraphStore, tmp_path: str) -> str:
    """Populate graph with session data."""
    projects_dir = os.path.join(tmp_path, "projects")
    proj_dir = os.path.join(projects_dir, "-proj")
    _write_jsonl(
        os.path.join(proj_dir, "sess-1.jsonl"),
        [
            {
                "type": "user",
                "timestamp": "2026-03-30T12:00:00Z",
                "message": {"role": "user", "content": "fix bug"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-03-30T12:00:01Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-4-6",
                    "content": [
                        {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/src/main.py"}},
                        {
                            "type": "tool_use",
                            "id": "tu_2",
                            "name": "Edit",
                            "input": {
                                "file_path": "/src/main.py",
                                "old_string": "x",
                                "new_string": "y",
                            },
                        },
                        {"type": "tool_use", "id": "tu_3", "name": "Bash", "input": {"command": "pytest"}},
                    ],
                    "usage": {"input_tokens": 1000, "output_tokens": 500},
                },
            },
        ],
    )
    ckpt_db = os.path.join(tmp_path, "ckpt.db")
    etl = SessionETL(store.conn, ckpt_db)
    etl.ingest_all(projects_dir)
    return "/proj"  # project path


class TestGraphQueries:
    def test_intent_chain(self, queries: GraphQueries, populated: str) -> None:
        chain = queries.intent_chain("sess-1")
        assert len(chain) == 3
        assert isinstance(chain[0], ActionStep)
        kinds = [s.kind for s in chain]
        assert "read" in kinds
        assert "edit" in kinds
        assert "bash" in kinds

    def test_project_graph(self, queries: GraphQueries, populated: str) -> None:
        result = queries.project_graph(populated)
        assert isinstance(result, ProjectGraphResult)
        assert result.sessions >= 1
        assert result.actions >= 3
        assert result.files >= 1

    def test_workflow_patterns(self, queries: GraphQueries, populated: str) -> None:
        patterns = queries.workflow_patterns(populated)
        assert isinstance(patterns, list)
        if patterns:
            assert isinstance(patterns[0], WorkflowPattern)

    def test_file_history(self, queries: GraphQueries, populated: str) -> None:
        history = queries.file_history("/src/main.py")
        assert len(history) >= 2  # Read + Edit

    def test_cascading_impact_no_symbols(self, queries: GraphQueries, populated: str) -> None:
        result = queries.cascading_impact("tu_2")
        assert isinstance(result, ImpactResult)
        # No symbols indexed, so changed will be empty
        assert result.changed == ""

    def test_related_sessions_empty(self, queries: GraphQueries, populated: str) -> None:
        result = queries.related_sessions("sess-1")
        assert isinstance(result, list)

    def test_agent_behavior_empty(self, queries: GraphQueries) -> None:
        result = queries.agent_behavior("Explore")
        assert result == []

    def test_sessions_for_symbol_empty(self, queries: GraphQueries) -> None:
        result = queries.sessions_for_symbol("nonexistent")
        assert result == []

    def test_pr_blast_radius_empty(self, queries: GraphQueries) -> None:
        result = queries.pr_blast_radius(999)
        assert result.changed == []
