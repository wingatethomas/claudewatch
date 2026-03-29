"""GraphAnalytics — aggregate queries over the persistent graph store.

Provides project summaries, agent type distributions, activity rankings,
and data integrity checks. All queries run against the SQLite store
for consistent, indexed performance.
"""

from __future__ import annotations

from typing import Any

from claudewatch.backend.graph.models import NodeKind
from claudewatch.backend.graph.store import GraphStore


class GraphAnalytics:
    """Analytics queries over the graph store."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    def project_summary(self, proj_key: str) -> dict[str, Any]:
        """Get summary stats for a project: session count, agent count, max depth."""
        session_count = self._store.count_nodes(proj_key, NodeKind.SESSION)
        agent_count = self._store.count_nodes(proj_key, NodeKind.AGENT)

        max_depth = 0
        if agent_count > 0:
            agents = self._store.get_nodes_by_project(proj_key)
            for node in agents:
                if node["kind"] == NodeKind.AGENT.value:
                    depth = self._store.get_depth(node["node_id"])
                    max_depth = max(max_depth, depth)

        return {
            "proj_key": proj_key,
            "session_count": session_count,
            "agent_count": agent_count,
            "max_depth": max_depth,
        }

    def agent_type_distribution(self, proj_key: str | None = None) -> dict[str, int]:
        """Count agents by type, optionally filtered by project."""
        if proj_key:
            nodes = self._store.get_nodes_by_project(proj_key)
        else:
            nodes = self._store.get_nodes_by_kind(NodeKind.AGENT)

        dist: dict[str, int] = {}
        for node in nodes:
            if node["kind"] != NodeKind.AGENT.value:
                continue
            agent_type = node["metadata"].get("agent_type", "unknown")
            dist[agent_type] = dist.get(agent_type, 0) + 1
        return dist

    def most_active_projects(self, limit: int = 10) -> list[dict[str, Any]]:
        """Rank projects by total node count (sessions + agents)."""
        projects = self._store.get_all_projects()
        ranked: list[dict[str, Any]] = []

        for proj_key in projects:
            session_count = self._store.count_nodes(proj_key, NodeKind.SESSION)
            agent_count = self._store.count_nodes(proj_key, NodeKind.AGENT)
            ranked.append(
                {
                    "proj_key": proj_key,
                    "session_count": session_count,
                    "agent_count": agent_count,
                    "total_nodes": session_count + agent_count,
                }
            )

        ranked.sort(key=lambda x: -x["total_nodes"])
        return ranked[:limit]

    def agents_per_session(self, proj_key: str) -> dict[str, float]:
        """Compute min/max/avg agents per session for a project."""
        sessions = [n for n in self._store.get_nodes_by_project(proj_key) if n["kind"] == NodeKind.SESSION.value]
        if not sessions:
            return {"min": 0, "max": 0, "avg": 0.0}

        counts: list[int] = []
        for session in sessions:
            # Count full subtree, not just direct children
            subtree = self._store.get_subtree(session["node_id"])
            counts.append(len(subtree))

        return {
            "min": min(counts),
            "max": max(counts),
            "avg": sum(counts) / len(counts),
        }

    def recent_sessions(self, proj_key: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Get most recently updated sessions, optionally filtered by project."""
        if proj_key:
            nodes = self._store.get_nodes_by_project(proj_key)
            sessions = [n for n in nodes if n["kind"] == NodeKind.SESSION.value]
        else:
            sessions = self._store.get_nodes_by_kind(NodeKind.SESSION)

        sessions.sort(key=lambda x: -x["updated_at"])
        return sessions[:limit]

    def deepest_agent_chains(self, limit: int = 10) -> list[dict[str, Any]]:
        """Find agents with the deepest spawn chains (most levels of nesting)."""
        agents = self._store.get_nodes_by_kind(NodeKind.AGENT)
        with_depth: list[dict[str, Any]] = []

        for agent in agents:
            depth = self._store.get_depth(agent["node_id"])
            if depth > 0:
                entry = dict(agent)
                entry["depth"] = depth
                with_depth.append(entry)

        with_depth.sort(key=lambda x: -x["depth"])
        return with_depth[:limit]

    def orphan_agents(self) -> list[dict[str, Any]]:
        """Find agents with no parent edge — indicates a data integrity issue."""
        agents = self._store.get_nodes_by_kind(NodeKind.AGENT)
        orphans: list[dict[str, Any]] = []

        for agent in agents:
            parent = self._store.get_parent(agent["node_id"])
            if parent is None:
                orphans.append(agent)

        return orphans
