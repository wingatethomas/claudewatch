"""Graph models — Kuzu schema DDL, store lifecycle, and query result dataclasses."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import kuzu

log = logging.getLogger("claudewatch")

# --- Kuzu schema DDL ---

_NODE_TABLES = [
    "CREATE NODE TABLE IF NOT EXISTS Project(path STRING, name STRING, PRIMARY KEY(path))",
    "CREATE NODE TABLE IF NOT EXISTS File(path STRING, project STRING, language STRING, hash STRING, lines INT64, PRIMARY KEY(path))",
    "CREATE NODE TABLE IF NOT EXISTS Symbol(id STRING, name STRING, qualified_name STRING, kind STRING, file_path STRING, start_line INT64, end_line INT64, signature STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Session(id STRING, project STRING, branch STRING, model STRING, started_at STRING, ended_at STRING, input_tokens INT64, output_tokens INT64, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Agent(id STRING, session_id STRING, agent_type STRING, description STRING, status STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Action(id STRING, kind STRING, session_id STRING, file_path STRING, timestamp STRING, old_text STRING, new_text STRING, pattern STRING, command STRING, description STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS PR(url STRING, number INT64, repository STRING, PRIMARY KEY(url))",
]

_REL_TABLES = [
    "CREATE REL TABLE IF NOT EXISTS HAS_FILE(FROM Project TO File)",
    "CREATE REL TABLE IF NOT EXISTS DEFINES(FROM File TO Symbol)",
    "CREATE REL TABLE IF NOT EXISTS CONTAINS(FROM Symbol TO Symbol)",
    "CREATE REL TABLE IF NOT EXISTS CALLS(FROM Symbol TO Symbol, line INT64)",
    "CREATE REL TABLE IF NOT EXISTS IMPORTS(FROM File TO File, name STRING)",
    "CREATE REL TABLE IF NOT EXISTS IN_PROJECT(FROM Session TO Project)",
    "CREATE REL TABLE IF NOT EXISTS SPAWNS(FROM Session TO Agent)",
    "CREATE REL TABLE IF NOT EXISTS PERFORMS(FROM Session TO Action)",
    "CREATE REL TABLE IF NOT EXISTS TARGETS(FROM Action TO File)",
    "CREATE REL TABLE IF NOT EXISTS MODIFIES(FROM Action TO Symbol)",
    "CREATE REL TABLE IF NOT EXISTS REFERENCES(FROM Session TO PR)",
    "CREATE REL TABLE IF NOT EXISTS NEXT(FROM Action TO Action)",
]


# --- Store lifecycle ---


class GraphStore:
    """Manages the Kuzu graph database lifecycle."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._db = kuzu.Database(db_path)
        self._conn = kuzu.Connection(self._db)
        self._create_schema()

    def _create_schema(self) -> None:
        for ddl in _NODE_TABLES:
            try:
                self._conn.execute(ddl)
            except RuntimeError:
                log.debug("graph schema: %s", ddl[:60])
        for ddl in _REL_TABLES:
            try:
                self._conn.execute(ddl)
            except RuntimeError:
                log.debug("graph schema: %s", ddl[:60])

    @property
    def conn(self) -> kuzu.Connection:
        return self._conn

    @property
    def db(self) -> kuzu.Database:
        return self._db

    @property
    def db_path(self) -> str:
        return self._db_path

    def close(self) -> None:
        self._conn.close()


# --- Return type dataclasses ---


@dataclass(frozen=True)
class ActionStep:
    kind: str
    file_path: str
    timestamp: str


@dataclass(frozen=True)
class ImpactResult:
    changed: str
    impacted: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HotspotResult:
    qualified_name: str
    file_path: str
    edits: int


@dataclass(frozen=True)
class RelatedSessionResult:
    session_id: str
    branch: str
    shared_symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BehaviorResult:
    kind: str
    frequency: int


@dataclass(frozen=True)
class ProjectGraphResult:
    files: int
    symbols: int
    sessions: int
    actions: int


@dataclass(frozen=True)
class PRImpactResult:
    changed: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowPattern:
    first: str
    then: str
    frequency: int


@dataclass(frozen=True)
class FileHistoryResult:
    session_id: str
    action_kind: str
    timestamp: str


@dataclass(frozen=True)
class SymbolNode:
    id: str
    name: str
    qualified_name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
