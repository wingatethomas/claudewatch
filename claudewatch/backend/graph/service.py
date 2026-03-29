"""AgentGraphService — builds relationship graphs from scanned session data.

Orchestrates SubagentScanner to discover agents, then assembles typed graph
structures (SessionGraph, ProjectGraph) for consumption by the UI layer.

Also syncs discovered data to the persistent GraphStore for historical queries.
"""

from __future__ import annotations

import logging

from claudewatch.backend.core.models import ClaudeSession
from claudewatch.backend.core.paths import cwd_to_proj_key
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.graph.models import (
    AgentNodeDTO,
    EdgeKind,
    GraphEdgeDTO,
    NodeKind,
    ProjectGraph,
    ScannedAgentDTO,
    SessionGraph,
    SessionNodeDTO,
)
from claudewatch.backend.graph.scanner import SubagentScanner
from claudewatch.backend.graph.store import GraphStore

log = logging.getLogger("claudewatch")


class AgentGraphService(BaseService):
    """Builds and queries agent relationship graphs.

    The service operates in two modes:
    1. In-memory graph building (build_session_graph, build_project_graph)
       for real-time UI display
    2. Persistent storage sync (sync_to_store) for historical queries
    """

    def __init__(self, scanner: SubagentScanner, store: GraphStore | None = None) -> None:
        super().__init__()
        self._scanner = scanner
        self._store = store

    def build_session_graph(self, proj_key: str, session_id: str) -> SessionGraph:
        """Build a graph for a single session and its subagents."""
        session_node = SessionNodeDTO(
            session_id=session_id,
            proj_key=proj_key,
        )

        scanned = self._scanner.scan_session(proj_key, session_id)

        agent_nodes: list[AgentNodeDTO] = []
        edges: list[GraphEdgeDTO] = []

        for agent in scanned:
            agent_node = AgentNodeDTO(
                agent_id=agent.agent_id,
                agent_type=agent.agent_type,
                description=agent.description,
                parent_uuid=agent.parent_uuid,
                session_id=agent.session_id,
                last_active=agent.last_active,
                started_at=agent.started_at,
                ended_at=agent.ended_at,
                entry_count=agent.entry_count,
                status=agent.status,
            )
            agent_nodes.append(agent_node)

            # Edge: session spawns agent
            edges.append(
                GraphEdgeDTO(
                    source=session_id,
                    target=agent.agent_id,
                    kind=EdgeKind.SPAWNS,
                )
            )

        graph = SessionGraph(
            session_node=session_node,
            agent_nodes=agent_nodes,
            edges=edges,
        )

        # Persist if store is available
        if self._store:
            self._sync_session_to_store(graph)

        return graph

    def build_project_graph(self, proj_key: str) -> ProjectGraph:
        """Build a graph for all sessions in a project, including worktrees."""
        session_ids = self._scanner.list_sessions(proj_key)
        session_graphs: list[SessionGraph] = []

        for session_id in session_ids:
            session_graph = self.build_session_graph(proj_key, session_id)
            session_graphs.append(session_graph)

        worktrees = self._scanner.find_worktree_projects(proj_key)
        worktree_branches = [wt.branch for wt in worktrees]

        # Also build graphs for worktree sessions
        for worktree in worktrees:
            wt_session_ids = self._scanner.list_sessions(worktree.proj_key)
            for wt_session_id in wt_session_ids:
                wt_graph = self.build_session_graph(worktree.proj_key, wt_session_id)
                session_graphs.append(wt_graph)

        return ProjectGraph(
            proj_key=proj_key,
            session_graphs=session_graphs,
            worktree_branches=worktree_branches,
        )

    def enrich_sessions(self, sessions: list[ClaudeSession]) -> None:
        """Enrich detected sessions with agent counts from disk.

        Sets agent_count on each session. Fast path: just counts files
        in the subagents directory without parsing JSONL content.
        Safe to call from background thread.
        """
        for session in sessions:
            if not session.cwd or not session.session_id:
                continue
            try:
                proj_key = cwd_to_proj_key(session.cwd)
                session.agent_count = self._scanner.count_agents(proj_key, session.session_id)
            except Exception:
                log.debug("graph: failed to count agents for %s", session.session_id, exc_info=True)

    def get_agent_details(self, cwd: str, session_id: str) -> list[ScannedAgentDTO]:
        """Get full agent details for a session. Used by the menu submenu."""
        if not cwd or not session_id:
            return []
        try:
            proj_key = cwd_to_proj_key(cwd)
            return self._scanner.scan_session(proj_key, session_id)
        except Exception:
            log.debug("graph: failed to get agent details for %s", session_id, exc_info=True)
            return []

    def _sync_session_to_store(self, graph: SessionGraph) -> None:
        """Persist a session graph to the SQLite store."""
        if not self._store:
            return

        try:
            with self._store.batch():
                self._store.upsert_node(
                    node_id=graph.session_node.session_id,
                    kind=NodeKind.SESSION,
                    label=graph.session_node.proj_key,
                    proj_key=graph.session_node.proj_key,
                )

                for agent in graph.agent_nodes:
                    self._store.upsert_node(
                        node_id=agent.agent_id,
                        kind=NodeKind.AGENT,
                        label=agent.description or agent.agent_type,
                        proj_key=graph.session_node.proj_key,
                        metadata={
                            "agent_type": agent.agent_type,
                            "description": agent.description,
                            "parent_uuid": agent.parent_uuid,
                            "last_active": agent.last_active,
                            "started_at": agent.started_at,
                            "ended_at": agent.ended_at,
                            "entry_count": agent.entry_count,
                            "status": agent.status.value if hasattr(agent.status, "value") else str(agent.status),
                        },
                    )

                for edge in graph.edges:
                    self._store.add_edge(edge.source, edge.target, edge.kind)

        except Exception:
            log.warning("graph: failed to sync session %s to store", graph.session_node.session_id, exc_info=True)
