"""Analytics store — SQLite connection, schema DDL, migrations."""

from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger("claudewatch")

_SCHEMA_VERSION = 1

_TABLES = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY,
    session_id      TEXT NOT NULL,
    uuid            TEXT UNIQUE,
    parent_uuid     TEXT,
    entry_type      TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    ts_epoch        REAL NOT NULL,
    proj_key        TEXT NOT NULL,
    git_branch      TEXT,
    model           TEXT,
    is_sidechain    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tools (
    id              INTEGER PRIMARY KEY,
    event_id        INTEGER REFERENCES events(id),
    session_id      TEXT NOT NULL,
    name            TEXT NOT NULL,
    tool_use_id     TEXT,
    file_path       TEXT,
    command         TEXT,
    pattern         TEXT,
    timestamp       TEXT NOT NULL,
    ts_epoch        REAL NOT NULL,
    proj_key        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id              INTEGER PRIMARY KEY,
    tool_id         INTEGER REFERENCES tools(id),
    session_id      TEXT NOT NULL,
    path            TEXT NOT NULL,
    access_type     TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    ts_epoch        REAL NOT NULL,
    proj_key        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens (
    id              INTEGER PRIMARY KEY,
    event_id        INTEGER REFERENCES events(id),
    session_id      TEXT NOT NULL,
    model           TEXT NOT NULL,
    input           INTEGER DEFAULT 0,
    output          INTEGER DEFAULT 0,
    cache_create    INTEGER DEFAULT 0,
    cache_read      INTEGER DEFAULT 0,
    timestamp       TEXT NOT NULL,
    ts_epoch        REAL NOT NULL,
    proj_key        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pull_requests (
    id              INTEGER PRIMARY KEY,
    session_id      TEXT NOT NULL,
    number          INTEGER NOT NULL,
    url             TEXT NOT NULL,
    repository      TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    ts_epoch        REAL NOT NULL,
    proj_key        TEXT NOT NULL,
    UNIQUE(session_id, url)
);

CREATE TABLE IF NOT EXISTS agents (
    id              INTEGER PRIMARY KEY,
    agent_id        TEXT UNIQUE NOT NULL,
    session_id      TEXT NOT NULL,
    parent_agent_id TEXT,
    agent_type      TEXT NOT NULL,
    description     TEXT DEFAULT '',
    status          TEXT DEFAULT 'stale',
    started_at      TEXT,
    ended_at        TEXT,
    entry_count     INTEGER DEFAULT 0,
    proj_key        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    proj_key        TEXT NOT NULL,
    first_ts        TEXT,
    last_ts         TEXT,
    first_epoch     REAL,
    last_epoch      REAL,
    user_messages   INTEGER DEFAULT 0,
    asst_messages   INTEGER DEFAULT 0,
    tool_count      INTEGER DEFAULT 0,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cache_tokens    INTEGER DEFAULT 0,
    primary_model   TEXT,
    primary_branch  TEXT,
    agent_count     INTEGER DEFAULT 0,
    updated_at      REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS checkpoints (
    file_path       TEXT PRIMARY KEY,
    byte_offset     INTEGER DEFAULT 0,
    line_count      INTEGER DEFAULT 0,
    file_size       INTEGER DEFAULT 0,
    file_mtime      REAL DEFAULT 0,
    updated_at      REAL DEFAULT 0
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_events_proj_ts ON events(proj_key, ts_epoch);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_tools_proj_name ON tools(proj_key, name);
CREATE INDEX IF NOT EXISTS idx_tools_session ON tools(session_id);
CREATE INDEX IF NOT EXISTS idx_tools_event ON tools(event_id);
CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_id);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
CREATE INDEX IF NOT EXISTS idx_tokens_session ON tokens(session_id);
CREATE INDEX IF NOT EXISTS idx_tokens_event ON tokens(event_id);
CREATE INDEX IF NOT EXISTS idx_pull_requests_session ON pull_requests(session_id);
CREATE INDEX IF NOT EXISTS idx_agents_session ON agents(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_proj ON sessions(proj_key);
"""


class AnalyticsStore:
    """Manages the analytics SQLite database."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._create_schema()

    def _configure(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    def _create_schema(self) -> None:
        self._conn.executescript(_TABLES)
        self._conn.executescript(_INDEXES)
        self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (_SCHEMA_VERSION,),
            )
            self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    @property
    def db_path(self) -> str:
        return self._db_path

    def close(self) -> None:
        self._conn.close()
