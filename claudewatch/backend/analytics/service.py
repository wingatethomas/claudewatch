"""Analytics service — thin facade coordinating store, ingest, scanner, queries."""

from __future__ import annotations

import logging
from typing import Protocol

from claudewatch.backend.analytics.ingest import Ingest
from claudewatch.backend.analytics.models import AgentInfo
from claudewatch.backend.analytics.queries import Queries
from claudewatch.backend.analytics.scanner import AgentScanner
from claudewatch.backend.analytics.store import AnalyticsStore
from claudewatch.backend.core.paths import cwd_to_proj_key
from claudewatch.backend.core.service import BaseService

log = logging.getLogger("claudewatch")


class _Enrichable(Protocol):
    cwd: str
    session_id: str
    agent_count: int


class AnalyticsService(BaseService):
    """Coordinates analytics ingestion, scanning, and queries."""

    def __init__(self, db_path: str, projects_dir: str) -> None:
        self._store = AnalyticsStore(db_path)
        self._ingest = Ingest(self._store.session)
        self._scanner = AgentScanner(self._store.session, projects_dir)
        self._queries = Queries(self._store.session)
        self._projects_dir = projects_dir

    # --- ETL (background thread) ---

    def full_scan(self) -> dict[str, int]:
        """Full re-ingest of all JSONL files + agent scan."""
        stats = self._ingest.full_scan(self._projects_dir)
        self._scanner.scan_all()
        return stats

    def incremental_scan(self) -> dict[str, int]:
        """Incremental ingest of changed JSONL files."""
        return self._ingest.incremental_scan(self._projects_dir)

    # --- Enrichment (background thread, called from detection) ---

    def enrich_sessions(self, sessions: list[_Enrichable]) -> None:
        """Add agent_count to session objects."""
        for s in sessions:
            if not s.cwd or not s.session_id:
                continue
            try:
                s.agent_count = self._scanner.count_agents(
                    cwd_to_proj_key(s.cwd),
                    s.session_id,
                )
            except Exception:
                log.debug("enrich_sessions: error for %s", s.session_id)

    # --- Agent details (main thread, for menu submenu) ---

    def agents_for_session(self, session_id: str) -> list[AgentInfo]:
        return self._scanner.agents_for_session(session_id)

    # --- Queries ---

    @property
    def queries(self) -> Queries:
        return self._queries

    def close(self) -> None:
        self._store.close()
