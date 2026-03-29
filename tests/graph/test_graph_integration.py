"""Integration tests — scanner → service → store pipeline."""

import json
import os

import pytest

from claudewatch.backend.graph.models import NodeKind
from claudewatch.backend.graph.scanner import SubagentScanner
from claudewatch.backend.graph.service import AgentGraphService
from claudewatch.backend.graph.store import GraphStore


def _write_jsonl(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


@pytest.fixture
def full_setup(tmp_path: str) -> tuple[str, str]:
    """Create projects dir + db path."""
    projects = os.path.join(tmp_path, "projects")
    proj = os.path.join(projects, "-Users-dev-myapp")
    session_id = "sess-integration-001"

    # Parent session
    _write_jsonl(
        os.path.join(proj, f"{session_id}.jsonl"),
        [
            {"type": "user", "message": {"role": "user", "content": "hello"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "Agent", "input": {"description": "search"}},
                    ],
                },
                "uuid": "parent-msg-001",
                "sessionId": session_id,
            },
        ],
    )

    # Child agent
    subagents = os.path.join(proj, session_id, "subagents")
    _write_jsonl(
        os.path.join(subagents, "agent-integ01.jsonl"),
        [{"parentUuid": "parent-msg-001", "sessionId": session_id, "message": {"role": "assistant"}}],
    )
    _write_json(
        os.path.join(subagents, "agent-integ01.meta.json"),
        {"agentType": "Explore", "description": "Search codebase"},
    )

    # Nested agent (agent spawns sub-agent)
    _write_jsonl(
        os.path.join(subagents, "agent-integ02.jsonl"),
        [{"parentUuid": "agent-msg-001", "sessionId": session_id, "message": {"role": "assistant"}}],
    )
    _write_json(
        os.path.join(subagents, "agent-integ02.meta.json"),
        {"agentType": "general-purpose", "description": "Run tests"},
    )

    db_path = os.path.join(tmp_path, "test_graph.db")
    return (str(projects), db_path)


class TestScannerToStoreIntegration:
    def test_service_syncs_to_store(self, full_setup: tuple[str, str]) -> None:
        projects_dir, db_path = full_setup
        scanner = SubagentScanner(projects_dir)
        store = GraphStore(db_path)
        service = AgentGraphService(scanner, store)

        graph = service.build_session_graph("-Users-dev-myapp", "sess-integration-001")

        # Verify in-memory graph
        assert graph.agent_count == 2

        # Verify persisted to store
        session_node = store.get_node("sess-integration-001")
        assert session_node is not None
        assert session_node["kind"] == "session"

        agent_node = store.get_node("integ01")
        assert agent_node is not None
        assert agent_node["kind"] == "agent"
        assert agent_node["metadata"]["agent_type"] == "Explore"

        # Verify edges
        children = store.get_children("sess-integration-001")
        assert len(children) == 2

        store.close()

    def test_project_graph_syncs_all_sessions(self, full_setup: tuple[str, str]) -> None:
        projects_dir, db_path = full_setup
        scanner = SubagentScanner(projects_dir)
        store = GraphStore(db_path)
        service = AgentGraphService(scanner, store)

        project_graph = service.build_project_graph("-Users-dev-myapp")

        assert len(project_graph.session_nodes) >= 1

        # All nodes should be in store
        all_nodes = store.get_nodes_by_project("-Users-dev-myapp")
        assert len(all_nodes) >= 3  # 1 session + 2 agents

        store.close()

    def test_incremental_sync(self, full_setup: tuple[str, str]) -> None:
        """Building the graph twice should not duplicate nodes."""
        projects_dir, db_path = full_setup
        scanner = SubagentScanner(projects_dir)
        store = GraphStore(db_path)
        service = AgentGraphService(scanner, store)

        service.build_session_graph("-Users-dev-myapp", "sess-integration-001")
        service.build_session_graph("-Users-dev-myapp", "sess-integration-001")

        sessions = store.get_nodes_by_kind(NodeKind.SESSION)
        assert len(sessions) == 1

        agents = store.get_nodes_by_kind(NodeKind.AGENT)
        assert len(agents) == 2

        store.close()

    def test_store_survives_reconnect(self, full_setup: tuple[str, str]) -> None:
        """Data persists across store instances."""
        projects_dir, db_path = full_setup
        scanner = SubagentScanner(projects_dir)

        store1 = GraphStore(db_path)
        service1 = AgentGraphService(scanner, store1)
        service1.build_session_graph("-Users-dev-myapp", "sess-integration-001")
        store1.close()

        # Reopen
        store2 = GraphStore(db_path)
        node = store2.get_node("sess-integration-001")
        assert node is not None

        children = store2.get_children("sess-integration-001")
        assert len(children) == 2
        store2.close()
