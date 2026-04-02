"""Graph store — Kuzu DB lifecycle, schema DDL, connection management."""

from __future__ import annotations

import logging
import os

import kuzu

log = logging.getLogger("claudewatch")

# Node table DDL
_NODE_TABLES = [
    "CREATE NODE TABLE IF NOT EXISTS Project(path STRING, name STRING, PRIMARY KEY(path))",
    "CREATE NODE TABLE IF NOT EXISTS File(path STRING, project STRING, language STRING, hash STRING, lines INT64, PRIMARY KEY(path))",
    "CREATE NODE TABLE IF NOT EXISTS Symbol(id STRING, name STRING, qualified_name STRING, kind STRING, file_path STRING, start_line INT64, end_line INT64, signature STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Session(id STRING, project STRING, branch STRING, model STRING, started_at STRING, ended_at STRING, input_tokens INT64, output_tokens INT64, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Agent(id STRING, session_id STRING, agent_type STRING, description STRING, status STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Action(id STRING, kind STRING, session_id STRING, file_path STRING, timestamp STRING, old_text STRING, new_text STRING, pattern STRING, command STRING, description STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS PR(url STRING, number INT64, repository STRING, PRIMARY KEY(url))",
]

# Relationship table DDL
_REL_TABLES = [
    # Code structure
    "CREATE REL TABLE IF NOT EXISTS HAS_FILE(FROM Project TO File)",
    "CREATE REL TABLE IF NOT EXISTS DEFINES(FROM File TO Symbol)",
    "CREATE REL TABLE IF NOT EXISTS CONTAINS(FROM Symbol TO Symbol)",
    "CREATE REL TABLE IF NOT EXISTS CALLS(FROM Symbol TO Symbol, line INT64)",
    "CREATE REL TABLE IF NOT EXISTS IMPORTS(FROM File TO File, name STRING)",
    # Activity
    "CREATE REL TABLE IF NOT EXISTS IN_PROJECT(FROM Session TO Project)",
    "CREATE REL TABLE IF NOT EXISTS SPAWNS(FROM Session TO Agent)",
    "CREATE REL TABLE IF NOT EXISTS PERFORMS(FROM Session TO Action)",
    "CREATE REL TABLE IF NOT EXISTS TARGETS(FROM Action TO File)",
    "CREATE REL TABLE IF NOT EXISTS MODIFIES(FROM Action TO Symbol)",
    "CREATE REL TABLE IF NOT EXISTS REFERENCES(FROM Session TO PR)",
    "CREATE REL TABLE IF NOT EXISTS NEXT(FROM Action TO Action)",
]


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
