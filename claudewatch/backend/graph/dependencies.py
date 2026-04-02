"""Graph service factory."""

import os
from functools import lru_cache

from claudewatch.backend.core.paths import CLAUDE_PROJECTS_DIR, DATA_DIR
from claudewatch.backend.graph.service import GraphService


@lru_cache(maxsize=1)
def get_graph_service() -> GraphService:
    db_path = os.path.join(DATA_DIR, "graph.kuzu")
    return GraphService(db_path, CLAUDE_PROJECTS_DIR)
