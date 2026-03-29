"""Tests for GraphStore — SQLite-backed persistent graph storage."""

import os

import pytest

from claudewatch.backend.graph.models import EdgeKind, NodeKind
from claudewatch.backend.graph.store import GraphStore


@pytest.fixture
def store(tmp_path: str) -> GraphStore:
    db_path = os.path.join(tmp_path, "graph.db")
    return GraphStore(db_path)


class TestGraphStore:
    def test_creates_database(self, store: GraphStore) -> None:
        assert os.path.exists(store.db_path)

    def test_upsert_session_node(self, store: GraphStore) -> None:
        store.upsert_node(
            node_id="sess-001",
            kind=NodeKind.SESSION,
            label="myapp",
            proj_key="-Users-dev-myapp",
            metadata={"model": "claude-opus-4-6"},
        )
        node = store.get_node("sess-001")
        assert node is not None
        assert node["kind"] == "session"
        assert node["label"] == "myapp"

    def test_upsert_agent_node(self, store: GraphStore) -> None:
        store.upsert_node(
            node_id="agent-abc",
            kind=NodeKind.AGENT,
            label="Explore auth module",
            proj_key="-Users-dev-myapp",
            metadata={"agent_type": "Explore", "parent_uuid": "uuid-001"},
        )
        node = store.get_node("agent-abc")
        assert node is not None
        assert node["kind"] == "agent"

    def test_upsert_is_idempotent(self, store: GraphStore) -> None:
        for _ in range(3):
            store.upsert_node(
                node_id="sess-001",
                kind=NodeKind.SESSION,
                label="myapp",
                proj_key="-Users-dev-myapp",
            )
        nodes = store.get_nodes_by_kind(NodeKind.SESSION)
        assert len(nodes) == 1

    def test_add_edge(self, store: GraphStore) -> None:
        store.upsert_node("sess-001", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("agent-abc", NodeKind.AGENT, "Explore", "-Users-dev-myapp")
        store.add_edge("sess-001", "agent-abc", EdgeKind.SPAWNS)

        edges = store.get_edges_from("sess-001")
        assert len(edges) == 1
        assert edges[0]["target"] == "agent-abc"
        assert edges[0]["kind"] == "spawns"

    def test_add_edge_idempotent(self, store: GraphStore) -> None:
        store.upsert_node("sess-001", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("agent-abc", NodeKind.AGENT, "Explore", "-Users-dev-myapp")
        for _ in range(3):
            store.add_edge("sess-001", "agent-abc", EdgeKind.SPAWNS)

        edges = store.get_edges_from("sess-001")
        assert len(edges) == 1

    def test_children_query(self, store: GraphStore) -> None:
        store.upsert_node("sess-001", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("agent-a", NodeKind.AGENT, "Explore", "-Users-dev-myapp")
        store.upsert_node("agent-b", NodeKind.AGENT, "Test", "-Users-dev-myapp")
        store.add_edge("sess-001", "agent-a", EdgeKind.SPAWNS)
        store.add_edge("sess-001", "agent-b", EdgeKind.SPAWNS)

        children = store.get_children("sess-001")
        assert len(children) == 2
        child_ids = {c["node_id"] for c in children}
        assert child_ids == {"agent-a", "agent-b"}

    def test_parent_query(self, store: GraphStore) -> None:
        store.upsert_node("sess-001", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("agent-a", NodeKind.AGENT, "Explore", "-Users-dev-myapp")
        store.add_edge("sess-001", "agent-a", EdgeKind.SPAWNS)

        parent = store.get_parent("agent-a")
        assert parent is not None
        assert parent["node_id"] == "sess-001"

    def test_nodes_by_project(self, store: GraphStore) -> None:
        store.upsert_node("sess-001", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("sess-002", NodeKind.SESSION, "other", "-Users-dev-other")
        store.upsert_node("agent-a", NodeKind.AGENT, "Explore", "-Users-dev-myapp")

        nodes = store.get_nodes_by_project("-Users-dev-myapp")
        assert len(nodes) == 2
        node_ids = {n["node_id"] for n in nodes}
        assert node_ids == {"sess-001", "agent-a"}

    def test_update_node_metadata(self, store: GraphStore) -> None:
        store.upsert_node("sess-001", NodeKind.SESSION, "myapp", "-Users-dev-myapp", {"status": "working"})
        store.upsert_node("sess-001", NodeKind.SESSION, "myapp", "-Users-dev-myapp", {"status": "idle"})

        node = store.get_node("sess-001")
        assert node["metadata"]["status"] == "idle"

    def test_delete_node_cascades_edges(self, store: GraphStore) -> None:
        store.upsert_node("sess-001", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("agent-a", NodeKind.AGENT, "Explore", "-Users-dev-myapp")
        store.add_edge("sess-001", "agent-a", EdgeKind.SPAWNS)

        store.delete_node("sess-001")

        assert store.get_node("sess-001") is None
        assert store.get_edges_from("sess-001") == []

    def test_agent_count_by_project(self, store: GraphStore) -> None:
        store.upsert_node("sess-001", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("agent-a", NodeKind.AGENT, "Explore", "-Users-dev-myapp")
        store.upsert_node("agent-b", NodeKind.AGENT, "Test", "-Users-dev-myapp")
        store.upsert_node("agent-c", NodeKind.AGENT, "Other", "-Users-dev-other")

        count = store.count_nodes("-Users-dev-myapp", NodeKind.AGENT)
        assert count == 2

    def test_session_count_by_project(self, store: GraphStore) -> None:
        store.upsert_node("sess-001", NodeKind.SESSION, "s1", "-Users-dev-myapp")
        store.upsert_node("sess-002", NodeKind.SESSION, "s2", "-Users-dev-myapp")

        count = store.count_nodes("-Users-dev-myapp", NodeKind.SESSION)
        assert count == 2

    def test_get_all_projects(self, store: GraphStore) -> None:
        store.upsert_node("sess-001", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("sess-002", NodeKind.SESSION, "other", "-Users-dev-other")

        projects = store.get_all_projects()
        assert len(projects) == 2
        assert "-Users-dev-myapp" in projects
        assert "-Users-dev-other" in projects

    def test_spawn_depth(self, store: GraphStore) -> None:
        """Test multi-level agent spawning: session -> agent -> sub-agent."""
        store.upsert_node("sess", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("agent-l1", NodeKind.AGENT, "L1", "-Users-dev-myapp")
        store.upsert_node("agent-l2", NodeKind.AGENT, "L2", "-Users-dev-myapp")
        store.add_edge("sess", "agent-l1", EdgeKind.SPAWNS)
        store.add_edge("agent-l1", "agent-l2", EdgeKind.SPAWNS)

        assert store.get_depth("sess") == 0
        assert store.get_depth("agent-l1") == 1
        assert store.get_depth("agent-l2") == 2

    def test_subtree(self, store: GraphStore) -> None:
        """Get full subtree below a node."""
        store.upsert_node("sess", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("a1", NodeKind.AGENT, "A1", "-Users-dev-myapp")
        store.upsert_node("a2", NodeKind.AGENT, "A2", "-Users-dev-myapp")
        store.upsert_node("a3", NodeKind.AGENT, "A3", "-Users-dev-myapp")
        store.add_edge("sess", "a1", EdgeKind.SPAWNS)
        store.add_edge("sess", "a2", EdgeKind.SPAWNS)
        store.add_edge("a1", "a3", EdgeKind.SPAWNS)

        subtree = store.get_subtree("sess")
        assert len(subtree) == 3  # a1, a2, a3 (not sess itself)
        subtree_ids = {n["node_id"] for n in subtree}
        assert subtree_ids == {"a1", "a2", "a3"}

    def test_empty_store(self, store: GraphStore) -> None:
        assert store.get_node("nonexistent") is None
        assert store.get_edges_from("nonexistent") == []
        assert store.get_children("nonexistent") == []
        assert store.get_all_projects() == []
