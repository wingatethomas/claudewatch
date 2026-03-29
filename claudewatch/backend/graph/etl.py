"""GraphETL — extract, transform, load pipeline for the agent graph.

Scans the Claude projects directory and ingests session/agent data into the
GraphStore. Supports both full scans and incremental updates using directory
mtime tracking to skip unchanged sessions.
"""

from __future__ import annotations

import logging
import os
import time

from claudewatch.backend.graph.models import EdgeKind, NodeKind
from claudewatch.backend.graph.scanner import SubagentScanner
from claudewatch.backend.graph.store import GraphStore

log = logging.getLogger("claudewatch")


class GraphETL:
    """Batch and incremental ingestion pipeline for the graph store."""

    def __init__(self, scanner: SubagentScanner, store: GraphStore) -> None:
        self._scanner = scanner
        self._store = store
        # Track last-scanned mtime per session dir for incremental scans
        self._session_mtimes: dict[str, float] = {}

    def full_scan(self) -> dict[str, int]:
        """Scan all projects and ingest everything. Returns stats."""
        stats: dict[str, int] = {"projects_scanned": 0, "sessions_ingested": 0, "agents_ingested": 0}
        projects = self._list_project_dirs()

        for proj_key in projects:
            stats["projects_scanned"] += 1
            session_ids = self._scanner.list_sessions(proj_key)

            for session_id in session_ids:
                agents = self._ingest_session(proj_key, session_id)
                stats["sessions_ingested"] += 1
                stats["agents_ingested"] += agents

                # Record mtime for incremental tracking
                session_dir = os.path.join(self._scanner._projects_dir, proj_key, session_id)
                self._session_mtimes[f"{proj_key}/{session_id}"] = _dir_mtime(session_dir)

        log.info(
            "graph etl: full scan — %d projects, %d sessions, %d agents",
            stats["projects_scanned"],
            stats["sessions_ingested"],
            stats["agents_ingested"],
        )
        return stats

    def incremental_scan(self) -> dict[str, int]:
        """Scan only sessions whose directories have changed since last scan."""
        stats: dict[str, int] = {"projects_scanned": 0, "sessions_ingested": 0, "agents_ingested": 0}
        projects = self._list_project_dirs()

        for proj_key in projects:
            stats["projects_scanned"] += 1
            session_ids = self._scanner.list_sessions(proj_key)

            for session_id in session_ids:
                key = f"{proj_key}/{session_id}"
                session_dir = os.path.join(self._scanner._projects_dir, proj_key, session_id)
                current_mtime = _dir_mtime(session_dir)
                last_mtime = self._session_mtimes.get(key, 0)

                if current_mtime <= last_mtime:
                    continue

                agents = self._ingest_session(proj_key, session_id)
                stats["sessions_ingested"] += 1
                stats["agents_ingested"] += agents
                self._session_mtimes[key] = current_mtime

        if stats["sessions_ingested"] > 0:
            log.info(
                "graph etl: incremental — %d sessions updated, %d agents",
                stats["sessions_ingested"],
                stats["agents_ingested"],
            )
        return stats

    def _ingest_session(self, proj_key: str, session_id: str) -> int:
        """Ingest a single session and its agents into the store. Returns agent count."""
        self._store.upsert_node(
            node_id=session_id,
            kind=NodeKind.SESSION,
            label=proj_key,
            proj_key=proj_key,
            metadata={"ingested_at": time.time()},
        )

        scanned_agents = self._scanner.scan_session(proj_key, session_id)
        for agent in scanned_agents:
            self._store.upsert_node(
                node_id=agent.agent_id,
                kind=NodeKind.AGENT,
                label=agent.description or agent.agent_type,
                proj_key=proj_key,
                metadata={
                    "agent_type": agent.agent_type,
                    "description": agent.description,
                    "parent_uuid": agent.parent_uuid,
                    "last_active": agent.last_active,
                },
            )
            self._store.add_edge(session_id, agent.agent_id, EdgeKind.SPAWNS)

        return len(scanned_agents)

    def _list_project_dirs(self) -> list[str]:
        """List all project directory keys from the projects directory."""
        try:
            entries = os.listdir(self._scanner._projects_dir)
        except OSError:
            return []

        return [e for e in entries if os.path.isdir(os.path.join(self._scanner._projects_dir, e))]


def _dir_mtime(path: str) -> float:
    """Get the most recent mtime of a directory or its contents."""
    try:
        if os.path.isdir(path):
            # Check the subagents dir specifically since that's what changes
            subagents = os.path.join(path, "subagents")
            if os.path.isdir(subagents):
                return max(os.path.getmtime(path), os.path.getmtime(subagents))
            return os.path.getmtime(path)
        return 0
    except OSError:
        return 0
