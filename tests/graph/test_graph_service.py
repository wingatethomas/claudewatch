"""Tests for AgentGraphService — session/agent relationship graph."""

import json
import os

import pytest

from claudewatch.backend.graph.models import AgentNodeDTO, EdgeKind, NodeKind, SessionNodeDTO
from claudewatch.backend.graph.scanner import SubagentScanner
from claudewatch.backend.graph.service import AgentGraphService


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
def projects_dir(tmp_path: str) -> str:
    """Create a mock ~/.claude/projects/ structure with parent + child sessions."""
    proj = os.path.join(tmp_path, "-Users-dev-myapp")
    session_id = "aaaa-bbbb-cccc-dddd"

    # Parent session JSONL
    _write_jsonl(
        os.path.join(proj, f"{session_id}.jsonl"),
        [
            {"type": "user", "message": {"role": "user", "content": "Fix the auth bug"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-4-6",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_001",
                            "name": "Agent",
                            "input": {
                                "description": "Explore auth module",
                                "subagent_type": "Explore",
                                "prompt": "Find all auth files",
                            },
                        },
                    ],
                },
                "uuid": "parent-uuid-001",
                "sessionId": session_id,
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-4-6",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_002",
                            "name": "Agent",
                            "input": {
                                "description": "Run test suite",
                                "subagent_type": "general-purpose",
                                "prompt": "Run pytest",
                            },
                        },
                    ],
                },
                "uuid": "parent-uuid-002",
                "sessionId": session_id,
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-4-6",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_003",
                            "name": "Read",
                            "input": {"file_path": "/src/auth.py"},
                        },
                    ],
                },
                "uuid": "parent-uuid-003",
                "sessionId": session_id,
            },
        ],
    )

    # Subagent files
    subagents_dir = os.path.join(proj, session_id, "subagents")

    _write_jsonl(
        os.path.join(subagents_dir, "agent-abc123.jsonl"),
        [
            {
                "parentUuid": "parent-uuid-001",
                "sessionId": session_id,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Found auth.py and auth_utils.py"}],
                },
            },
        ],
    )
    _write_json(
        os.path.join(subagents_dir, "agent-abc123.meta.json"),
        {"agentType": "Explore", "description": "Explore auth module"},
    )

    _write_jsonl(
        os.path.join(subagents_dir, "agent-def456.jsonl"),
        [
            {
                "parentUuid": "parent-uuid-002",
                "sessionId": session_id,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}},
                    ],
                },
            },
        ],
    )
    _write_json(
        os.path.join(subagents_dir, "agent-def456.meta.json"),
        {"agentType": "general-purpose", "description": "Run test suite"},
    )

    return str(tmp_path)


@pytest.fixture
def worktree_dir(tmp_path: str) -> str:
    """Create a mock worktree session structure."""
    proj = os.path.join(tmp_path, "-Users-dev-myapp--claude-worktrees-feature-branch")
    session_id = "wwww-xxxx-yyyy-zzzz"

    _write_jsonl(
        os.path.join(proj, f"{session_id}.jsonl"),
        [
            {"type": "user", "message": {"role": "user", "content": "Implement feature"}},
        ],
    )

    return str(tmp_path)


class TestSubagentScanner:
    def test_finds_subagent_files(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        agents = scanner.scan_session("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")
        assert len(agents) == 2

    def test_extracts_agent_id(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        agents = scanner.scan_session("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")
        agent_ids = {a.agent_id for a in agents}
        assert "abc123" in agent_ids
        assert "def456" in agent_ids

    def test_extracts_agent_type(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        agents = scanner.scan_session("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")
        by_id = {a.agent_id: a for a in agents}
        assert by_id["abc123"].agent_type == "Explore"
        assert by_id["def456"].agent_type == "general-purpose"

    def test_extracts_description(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        agents = scanner.scan_session("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")
        by_id = {a.agent_id: a for a in agents}
        assert by_id["abc123"].description == "Explore auth module"
        assert by_id["def456"].description == "Run test suite"

    def test_extracts_parent_uuid(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        agents = scanner.scan_session("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")
        by_id = {a.agent_id: a for a in agents}
        assert by_id["abc123"].parent_uuid == "parent-uuid-001"
        assert by_id["def456"].parent_uuid == "parent-uuid-002"

    def test_empty_subagents_dir(self, tmp_path: str) -> None:
        proj = os.path.join(tmp_path, "-Users-dev-empty")
        os.makedirs(proj)
        _write_jsonl(os.path.join(proj, "sess.jsonl"), [])
        scanner = SubagentScanner(str(tmp_path))
        agents = scanner.scan_session("-Users-dev-empty", "sess")
        assert agents == []

    def test_missing_meta_file(self, tmp_path: str) -> None:
        proj = os.path.join(tmp_path, "-Users-dev-nometa")
        subagents = os.path.join(proj, "sess-id", "subagents")
        _write_jsonl(
            os.path.join(subagents, "agent-orphan.jsonl"),
            [{"parentUuid": "x", "sessionId": "sess-id", "message": {"role": "assistant"}}],
        )
        scanner = SubagentScanner(str(tmp_path))
        agents = scanner.scan_session("-Users-dev-nometa", "sess-id")
        assert len(agents) == 1
        assert agents[0].agent_type == "unknown"
        assert agents[0].description == ""

    def test_detects_worktree_projects(self, worktree_dir: str) -> None:
        scanner = SubagentScanner(worktree_dir)
        worktrees = scanner.find_worktree_projects("-Users-dev-myapp")
        assert len(worktrees) == 1
        assert worktrees[0].branch == "feature-branch"
        assert "--claude-worktrees-" in worktrees[0].proj_key


class TestAgentGraphService:
    def test_builds_graph_for_session(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        service = AgentGraphService(scanner)
        graph = service.build_session_graph("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")

        assert graph.session_node is not None
        assert graph.session_node.session_id == "aaaa-bbbb-cccc-dddd"

    def test_graph_contains_agents(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        service = AgentGraphService(scanner)
        graph = service.build_session_graph("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")

        assert len(graph.agent_nodes) == 2

    def test_graph_edges_link_session_to_agents(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        service = AgentGraphService(scanner)
        graph = service.build_session_graph("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")

        spawn_edges = [e for e in graph.edges if e.kind == EdgeKind.SPAWNS]
        assert len(spawn_edges) == 2
        for edge in spawn_edges:
            assert edge.source == "aaaa-bbbb-cccc-dddd"

    def test_children_of_session(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        service = AgentGraphService(scanner)
        graph = service.build_session_graph("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")

        children = graph.children_of("aaaa-bbbb-cccc-dddd")
        assert len(children) == 2
        assert all(isinstance(c, AgentNodeDTO) for c in children)

    def test_parent_of_agent(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        service = AgentGraphService(scanner)
        graph = service.build_session_graph("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")

        parent = graph.parent_of("abc123")
        assert parent is not None
        assert isinstance(parent, SessionNodeDTO)
        assert parent.session_id == "aaaa-bbbb-cccc-dddd"

    def test_agent_count(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        service = AgentGraphService(scanner)
        graph = service.build_session_graph("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")

        assert graph.agent_count == 2

    def test_empty_session_has_no_agents(self, tmp_path: str) -> None:
        proj = os.path.join(tmp_path, "-Users-dev-empty")
        os.makedirs(proj)
        _write_jsonl(os.path.join(proj, "empty-sess.jsonl"), [])

        scanner = SubagentScanner(str(tmp_path))
        service = AgentGraphService(scanner)
        graph = service.build_session_graph("-Users-dev-empty", "empty-sess")

        assert graph.agent_count == 0
        assert graph.edges == []

    def test_agent_activity_from_mtime(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        agents = scanner.scan_session("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")
        # All agents should have a last_active timestamp from file mtime
        for agent in agents:
            assert agent.last_active > 0

    def test_node_kinds(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        service = AgentGraphService(scanner)
        graph = service.build_session_graph("-Users-dev-myapp", "aaaa-bbbb-cccc-dddd")

        assert graph.session_node.kind == NodeKind.SESSION
        for agent in graph.agent_nodes:
            assert agent.kind == NodeKind.AGENT


class TestProjectGraph:
    def test_builds_project_graph(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        service = AgentGraphService(scanner)
        graph = service.build_project_graph("-Users-dev-myapp")

        assert len(graph.session_nodes) >= 1

    def test_project_graph_includes_agents(self, projects_dir: str) -> None:
        scanner = SubagentScanner(projects_dir)
        service = AgentGraphService(scanner)
        graph = service.build_project_graph("-Users-dev-myapp")

        total_agents = sum(len(sg.agent_nodes) for sg in graph.session_graphs)
        assert total_agents == 2

    def test_project_graph_includes_worktrees(self, projects_dir: str, worktree_dir: str) -> None:
        # Merge both fixtures into one dir
        import shutil

        for name in os.listdir(worktree_dir):
            src = os.path.join(worktree_dir, name)
            dst = os.path.join(projects_dir, name)
            if os.path.isdir(src) and not os.path.exists(dst):
                shutil.copytree(src, dst)

        scanner = SubagentScanner(projects_dir)
        service = AgentGraphService(scanner)
        graph = service.build_project_graph("-Users-dev-myapp")

        assert graph.worktree_count >= 1
