"""Graph service — orchestrates repository operations and background lifecycle."""

from __future__ import annotations

import logging
import os

from claudewatch.backend.core import features
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.graph.models import GraphStore
from claudewatch.backend.graph.repository import CodeETL, EditMapper, GraphQueries, SessionETL

log = logging.getLogger("claudewatch")

# Feature flag for AST-based code indexing
features.register(
    features.Feature(
        key="code_indexing",
        description="Index source files for change impact analysis",
        default_enabled=False,
    )
)


class GraphService(BaseService):
    """Coordinates graph ETL pipelines, mapper, and queries."""

    def __init__(self, db_path: str, projects_dir: str) -> None:
        self._store = GraphStore(db_path)
        parent = os.path.dirname(db_path)
        checkpoint_db = os.path.join(parent, "graph_checkpoints.db")
        self._session_etl = SessionETL(self._store.conn, checkpoint_db)
        self._code_etl = CodeETL(self._store.conn)
        self._mapper = EditMapper(self._store.conn)
        self._queries = GraphQueries(self._store.conn)
        self._projects_dir = projects_dir

    # --- ETL (background thread) ---

    def ingest_sessions(self) -> dict[str, int]:
        """Run session JSONL ingestion."""
        return self._session_etl.ingest_all(self._projects_dir)

    def index_code(self, project_path: str) -> int:
        """Index source files for a project. Returns symbol count."""
        return self._code_etl.index_project(project_path)

    def map_edits(self) -> int:
        """Link edit actions to the symbols they modified."""
        return self._mapper.map_all()

    _catchup_done = False

    def full_pipeline(self) -> dict[str, int]:
        """Run the complete ETL pipeline: sessions → code indexing → mapper."""
        # One-time catch-up: clear checkpoints so all existing JSONL files get
        # ingested into the graph, not just ones modified since graph wiring landed.
        if not GraphService._catchup_done:
            GraphService._catchup_done = True
            self._session_etl.clear_checkpoints()
            log.info("graph: cleared checkpoints for full catch-up scan")
        stats = self.ingest_sessions()
        if features.is_enabled("code_indexing"):
            for project_path in self._get_active_project_paths():
                if os.path.isdir(project_path):
                    self._code_etl.index_project(project_path)
            self._mapper.map_all()
        return stats

    def _get_active_project_paths(self) -> list[str]:
        return self._queries.active_project_paths()

    # --- Queries ---

    @property
    def queries(self) -> GraphQueries:
        return self._queries

    def close(self) -> None:
        self._session_etl.close()
        self._store.close()
