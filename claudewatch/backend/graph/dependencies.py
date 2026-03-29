"""Graph service factory."""

import os
from functools import lru_cache

from claudewatch.backend.core.paths import CLAUDE_PROJECTS_DIR, DATA_DIR
from claudewatch.backend.graph.etl import GraphETL
from claudewatch.backend.graph.scanner import SubagentScanner
from claudewatch.backend.graph.service import AgentGraphService
from claudewatch.backend.graph.store import GraphStore


@lru_cache(maxsize=1)
def get_graph_store() -> GraphStore:
    return GraphStore(os.path.join(DATA_DIR, "graph.db"))


@lru_cache(maxsize=1)
def get_subagent_scanner() -> SubagentScanner:
    return SubagentScanner(CLAUDE_PROJECTS_DIR)


@lru_cache(maxsize=1)
def get_graph_service() -> AgentGraphService:
    return AgentGraphService(get_subagent_scanner(), get_graph_store())


@lru_cache(maxsize=1)
def get_graph_etl() -> GraphETL:
    return GraphETL(get_subagent_scanner(), get_graph_store())
