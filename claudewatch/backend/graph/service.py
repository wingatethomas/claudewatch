"""Graph service — orchestrates repository operations and background lifecycle."""

from __future__ import annotations

import logging
import os

from claudewatch.backend.core.service import BaseService
from claudewatch.backend.graph.models import GraphStore
from claudewatch.backend.graph.repository import CodeETL, EditMapper, GraphQueries, SessionETL

log = logging.getLogger("claudewatch")


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

    def full_pipeline(self) -> dict[str, int]:
        """Run the complete ETL pipeline: sessions → code → mapper."""
        stats = self.ingest_sessions()
        self.map_edits()
        return stats

    # --- Queries ---

    @property
    def queries(self) -> GraphQueries:
        return self._queries

    def close(self) -> None:
        self._session_etl.close()
        self._store.close()
