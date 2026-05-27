"""Analytics models — ORM schema, return type dataclasses, and store lifecycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import Float, Index, Integer, Text, UniqueConstraint, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

log = logging.getLogger("claudewatch")

_SCHEMA_VERSION = 1

# --- Tool metadata (shared between ingest and queries) ---

FILE_TOOLS: dict[str, str] = {
    "Read": "file_path",
    "Edit": "file_path",
    "Write": "file_path",
    "Grep": "path",
    "Glob": "path",
    "NotebookEdit": "file_path",
}

ACCESS_TYPE: dict[str, str] = {
    "Read": "read",
    "Edit": "edit",
    "Write": "write",
    "Grep": "grep",
    "Glob": "glob",
    "NotebookEdit": "edit",
}


# --- ORM base ---


class Base(DeclarativeBase):
    pass


# --- ORM row models ---


class EventRow(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    uuid: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    parent_uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    ts_epoch: Mapped[float] = mapped_column(Float, nullable=False)
    proj_key: Mapped[str] = mapped_column(Text, nullable=False)
    git_branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_sidechain: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("idx_events_proj_ts", "proj_key", "ts_epoch"),
        Index("idx_events_session", "session_id"),
    )


class ToolRow(Base):
    __tablename__ = "tools"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_use_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    ts_epoch: Mapped[float] = mapped_column(Float, nullable=False)
    proj_key: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_tools_proj_name", "proj_key", "name"),
        Index("idx_tools_session", "session_id"),
        Index("idx_tools_event", "event_id"),
    )


class FileRow(Base):
    __tablename__ = "files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tool_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    access_type: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    ts_epoch: Mapped[float] = mapped_column(Float, nullable=False)
    proj_key: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_files_session", "session_id"),
        Index("idx_files_path", "path"),
    )


class TokenRow(Base):
    __tablename__ = "tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[int] = mapped_column(Integer, default=0)
    output: Mapped[int] = mapped_column(Integer, default=0)
    cache_create: Mapped[int] = mapped_column(Integer, default=0)
    cache_read: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    ts_epoch: Mapped[float] = mapped_column(Float, nullable=False)
    proj_key: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_tokens_session", "session_id"),
        Index("idx_tokens_event", "event_id"),
    )


class PullRequestRow(Base):
    __tablename__ = "pull_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    repository: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    ts_epoch: Mapped[float] = mapped_column(Float, nullable=False)
    proj_key: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("session_id", "url"),
        Index("idx_pull_requests_session", "session_id"),
    )


class AgentRow(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    parent_agent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="stale")
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    ended_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_count: Mapped[int] = mapped_column(Integer, default=0)
    proj_key: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("idx_agents_session", "session_id"),)


class SessionRow(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    proj_key: Mapped[str] = mapped_column(Text, nullable=False)
    first_ts: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_ts: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_messages: Mapped[int] = mapped_column(Integer, default=0)
    asst_messages: Mapped[int] = mapped_column(Integer, default=0)
    tool_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_tokens: Mapped[int] = mapped_column(Integer, default=0)
    primary_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[float] = mapped_column(Float, default=0)

    __table_args__ = (Index("idx_sessions_proj", "proj_key"),)


class CheckpointRow(Base):
    __tablename__ = "checkpoints"
    file_path: Mapped[str] = mapped_column(Text, primary_key=True)
    byte_offset: Mapped[int] = mapped_column(Integer, default=0)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_mtime: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[float] = mapped_column(Float, default=0)


class SchemaVersionRow(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)


# --- SQLite pragmas ---


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn: object, _connection_record: object) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


# --- Store lifecycle ---


class AnalyticsStore:
    """Manages the analytics SQLite database via SQLAlchemy ORM."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)
        self._init_version()

    def _init_version(self) -> None:
        with self.session() as s:
            row = s.query(SchemaVersionRow).first()
            if row is None:
                s.add(SchemaVersionRow(version=_SCHEMA_VERSION))
                s.commit()

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def db_path(self) -> str:
        return self._db_path

    def session(self) -> Session:
        """Create a new ORM session."""
        return self._session_factory()

    def close(self) -> None:
        self._engine.dispose()


# --- Return type dataclasses ---


class AgentStatus(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    STALE = "stale"


@dataclass(frozen=True)
class ToolUsage:
    name: str
    count: int


@dataclass(frozen=True)
class FileUsage:
    path: str
    count: int
    last_accessed: str


@dataclass(frozen=True)
class TokenSummary:
    model: str
    input: int
    output: int
    cache: int
    total: int


@dataclass(frozen=True)
class TimeBucket:
    bucket: str
    value: int


@dataclass(frozen=True)
class SessionOverview:
    session_id: str
    proj_key: str
    first_ts: str
    last_ts: str
    user_messages: int
    asst_messages: int
    tool_count: int
    total_tokens: int
    primary_model: str
    primary_branch: str
    agent_count: int


@dataclass(frozen=True)
class PRLink:
    number: int
    url: str
    repository: str
    timestamp: str


@dataclass(frozen=True)
class GlobalSummary:
    total_sessions: int
    total_messages: int
    total_tools: int
    total_tokens: int
    total_agents: int


@dataclass(frozen=True)
class ProjectSummary:
    proj_key: str
    session_count: int
    agent_count: int
    tool_count: int


@dataclass(frozen=True)
class RelatedSession:
    session_id: str
    proj_key: str
    shared_files: int
    shared_file_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FileHotspot:
    path: str
    session_count: int
    total_accesses: int


@dataclass(frozen=True)
class ToolSequence:
    first: str
    second: str
    count: int


@dataclass(frozen=True)
class BranchActivity:
    branch: str
    session_count: int
    event_count: int
    last_active: str
