"""Tests for graph analytics — aggregate queries, project stats, ETL pipeline."""

import json
import os
import time

import pytest

from claudewatch.backend.graph.analytics import GraphAnalytics
from claudewatch.backend.graph.models import EdgeKind, NodeKind
from claudewatch.backend.graph.store import GraphStore


@pytest.fixture
def store(tmp_path: str) -> GraphStore:
    return GraphStore(os.path.join(tmp_path, "analytics.db"))


@pytest.fixture
def populated_store(store: GraphStore) -> GraphStore:
    """Store with realistic multi-project, multi-session data."""
    now = time.time()

    # Project 1: myapp — 3 sessions, 5 agents total
    store.upsert_node("sess-1", NodeKind.SESSION, "myapp", "-Users-dev-myapp", {"started_at": now - 3600})
    store.upsert_node("sess-2", NodeKind.SESSION, "myapp", "-Users-dev-myapp", {"started_at": now - 1800})
    store.upsert_node("sess-3", NodeKind.SESSION, "myapp", "-Users-dev-myapp", {"started_at": now - 600})

    store.upsert_node(
        "a1", NodeKind.AGENT, "Explore auth", "-Users-dev-myapp", {"agent_type": "Explore", "last_active": now - 3500}
    )
    store.upsert_node(
        "a2",
        NodeKind.AGENT,
        "Run tests",
        "-Users-dev-myapp",
        {"agent_type": "general-purpose", "last_active": now - 3400},
    )
    store.upsert_node(
        "a3", NodeKind.AGENT, "Search docs", "-Users-dev-myapp", {"agent_type": "Explore", "last_active": now - 1700}
    )
    store.upsert_node(
        "a4",
        NodeKind.AGENT,
        "Fix lint",
        "-Users-dev-myapp",
        {"agent_type": "general-purpose", "last_active": now - 500},
    )
    store.upsert_node(
        "a5", NodeKind.AGENT, "Deep research", "-Users-dev-myapp", {"agent_type": "Explore", "last_active": now - 400}
    )

    store.add_edge("sess-1", "a1", EdgeKind.SPAWNS)
    store.add_edge("sess-1", "a2", EdgeKind.SPAWNS)
    store.add_edge("sess-2", "a3", EdgeKind.SPAWNS)
    store.add_edge("sess-3", "a4", EdgeKind.SPAWNS)
    store.add_edge("sess-3", "a5", EdgeKind.SPAWNS)
    # Nested: a4 spawns a sub-agent
    store.upsert_node(
        "a6",
        NodeKind.AGENT,
        "Sub-lint check",
        "-Users-dev-myapp",
        {"agent_type": "general-purpose", "last_active": now - 450},
    )
    store.add_edge("a4", "a6", EdgeKind.SPAWNS)

    # Project 2: backend-api — 1 session, 1 agent
    store.upsert_node("sess-4", NodeKind.SESSION, "backend-api", "-Users-dev-backend-api", {"started_at": now - 7200})
    store.upsert_node(
        "a7",
        NodeKind.AGENT,
        "API review",
        "-Users-dev-backend-api",
        {"agent_type": "Explore", "last_active": now - 7100},
    )
    store.add_edge("sess-4", "a7", EdgeKind.SPAWNS)

    return store


class TestGraphAnalytics:
    def test_project_summary(self, populated_store: GraphStore) -> None:
        analytics = GraphAnalytics(populated_store)
        summary = analytics.project_summary("-Users-dev-myapp")

        assert summary["session_count"] == 3
        assert summary["agent_count"] == 6  # a1-a6
        assert summary["max_depth"] == 2  # sess-3 -> a4 -> a6

    def test_project_summary_empty(self, store: GraphStore) -> None:
        analytics = GraphAnalytics(store)
        summary = analytics.project_summary("-Users-dev-nonexistent")
        assert summary["session_count"] == 0
        assert summary["agent_count"] == 0

    def test_agent_type_distribution(self, populated_store: GraphStore) -> None:
        analytics = GraphAnalytics(populated_store)
        dist = analytics.agent_type_distribution("-Users-dev-myapp")

        assert dist["Explore"] == 3  # a1, a3, a5
        assert dist["general-purpose"] == 3  # a2, a4, a6

    def test_agent_type_distribution_all_projects(self, populated_store: GraphStore) -> None:
        analytics = GraphAnalytics(populated_store)
        dist = analytics.agent_type_distribution()

        assert dist["Explore"] == 4  # a1, a3, a5, a7
        assert dist["general-purpose"] == 3

    def test_most_active_projects(self, populated_store: GraphStore) -> None:
        analytics = GraphAnalytics(populated_store)
        projects = analytics.most_active_projects(limit=10)

        assert len(projects) == 2
        # myapp has more sessions+agents, should be first
        assert projects[0]["proj_key"] == "-Users-dev-myapp"
        assert projects[0]["total_nodes"] > projects[1]["total_nodes"]

    def test_agents_per_session(self, populated_store: GraphStore) -> None:
        analytics = GraphAnalytics(populated_store)
        stats = analytics.agents_per_session("-Users-dev-myapp")

        assert stats["avg"] > 0
        assert stats["max"] >= 2  # sess-1 and sess-3 each have 2+ agents
        assert stats["min"] >= 1

    def test_recent_sessions(self, populated_store: GraphStore) -> None:
        analytics = GraphAnalytics(populated_store)
        recent = analytics.recent_sessions(limit=2)

        assert len(recent) == 2
        # Ordered by updated_at (store insertion time), most recent first
        # sess-4 was inserted last so it's first
        assert recent[0]["node_id"] == "sess-4"

    def test_recent_sessions_by_project(self, populated_store: GraphStore) -> None:
        analytics = GraphAnalytics(populated_store)
        recent = analytics.recent_sessions(proj_key="-Users-dev-backend-api", limit=10)

        assert len(recent) == 1
        assert recent[0]["node_id"] == "sess-4"

    def test_deepest_agent_chains(self, populated_store: GraphStore) -> None:
        analytics = GraphAnalytics(populated_store)
        chains = analytics.deepest_agent_chains(limit=5)

        # a6 is at depth 2 (sess-3 -> a4 -> a6)
        assert any(c["node_id"] == "a6" and c["depth"] == 2 for c in chains)

    def test_orphan_agents(self, store: GraphStore) -> None:
        """Agents with no parent edge are orphans (data integrity issue)."""
        store.upsert_node("orphan-1", NodeKind.AGENT, "Lost agent", "-Users-dev-myapp")
        store.upsert_node("sess-1", NodeKind.SESSION, "myapp", "-Users-dev-myapp")
        store.upsert_node("a-ok", NodeKind.AGENT, "Good agent", "-Users-dev-myapp")
        store.add_edge("sess-1", "a-ok", EdgeKind.SPAWNS)

        analytics = GraphAnalytics(store)
        orphans = analytics.orphan_agents()

        assert len(orphans) == 1
        assert orphans[0]["node_id"] == "orphan-1"


class TestETLPipeline:
    def _make_projects_dir(self, tmp_path: str) -> str:
        """Create a multi-project fixture for ETL testing."""
        projects = os.path.join(tmp_path, "projects")

        # Project 1: 2 sessions, each with agents
        proj1 = os.path.join(projects, "-Users-dev-myapp")
        for session_id, agents in [("sess-a", ["x1", "x2"]), ("sess-b", ["y1"])]:
            self._write_session(proj1, session_id, agents)

        # Project 2: 1 session, no agents
        proj2 = os.path.join(projects, "-Users-dev-api")
        self._write_session(proj2, "sess-c", [])

        return projects

    @staticmethod
    def _write_session(proj_dir: str, session_id: str, agent_ids: list[str]) -> None:
        jsonl_path = os.path.join(proj_dir, f"{session_id}.jsonl")
        os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
        with open(jsonl_path, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n")

        for agent_id in agent_ids:
            subagents = os.path.join(proj_dir, session_id, "subagents")
            jsonl = os.path.join(subagents, f"agent-{agent_id}.jsonl")
            os.makedirs(os.path.dirname(jsonl), exist_ok=True)
            with open(jsonl, "w") as f:
                f.write(json.dumps({"parentUuid": "p", "sessionId": session_id}) + "\n")
            meta = os.path.join(subagents, f"agent-{agent_id}.meta.json")
            with open(meta, "w") as f:
                json.dump({"agentType": "Explore", "description": f"Agent {agent_id}"}, f)

    def test_full_scan_ingests_all(self, tmp_path: str) -> None:
        projects_dir = self._make_projects_dir(tmp_path)
        db_path = os.path.join(tmp_path, "etl.db")

        from claudewatch.backend.graph.etl import GraphETL
        from claudewatch.backend.graph.scanner import SubagentScanner

        scanner = SubagentScanner(projects_dir)
        store = GraphStore(db_path)
        etl = GraphETL(scanner, store)

        stats = etl.full_scan()

        assert stats["projects_scanned"] == 2
        assert stats["sessions_ingested"] == 3
        assert stats["agents_ingested"] == 3
        store.close()

    def test_incremental_scan_skips_unchanged(self, tmp_path: str) -> None:
        projects_dir = self._make_projects_dir(tmp_path)
        db_path = os.path.join(tmp_path, "etl.db")

        from claudewatch.backend.graph.etl import GraphETL
        from claudewatch.backend.graph.scanner import SubagentScanner

        scanner = SubagentScanner(projects_dir)
        store = GraphStore(db_path)
        etl = GraphETL(scanner, store)

        etl.full_scan()
        stats2 = etl.incremental_scan()

        # Second scan should detect nothing new
        assert stats2["sessions_ingested"] == 0
        assert stats2["agents_ingested"] == 0
        store.close()

    def test_incremental_picks_up_new_agents(self, tmp_path: str) -> None:
        projects_dir = self._make_projects_dir(tmp_path)
        db_path = os.path.join(tmp_path, "etl.db")

        from claudewatch.backend.graph.etl import GraphETL
        from claudewatch.backend.graph.scanner import SubagentScanner

        scanner = SubagentScanner(projects_dir)
        store = GraphStore(db_path)
        etl = GraphETL(scanner, store)

        etl.full_scan()

        # Add a new agent to an existing session
        subagents = os.path.join(projects_dir, "-Users-dev-myapp", "sess-a", "subagents")
        new_agent = os.path.join(subagents, "agent-new1.jsonl")
        with open(new_agent, "w") as f:
            f.write(json.dumps({"parentUuid": "p", "sessionId": "sess-a"}) + "\n")
        meta = os.path.join(subagents, "agent-new1.meta.json")
        with open(meta, "w") as f:
            json.dump({"agentType": "general-purpose", "description": "New agent"}, f)

        # Touch the session dir to trigger rescan
        import pathlib

        pathlib.Path(os.path.join(projects_dir, "-Users-dev-myapp", "sess-a")).touch()

        stats = etl.incremental_scan()
        assert stats["agents_ingested"] >= 1
        store.close()
